"""Subtitle Edit 5 플러그인 어댑터.

SE5 플러그인은 **독립 실행 파일 + JSON 파일** 방식이다. SE가 `request.json`을 쓰고
플러그인을 실행 파일 인자와 함께 띄우면, 플러그인이 일하고 `responseFilePath`에
`response.json`을 쓴 뒤 0으로 끝난다. SE는 그 결과로 **undo 지점을 만들고** 자막을
교체한다.

이 방식을 고른 이유: 사용자가 SE를 그대로 쓴다. 포맷 408종·파형·OCR·Whisper가
전부 남아 있고 거기에 규정 검사와 한국어 교정이 더해진다. 뺄셈 없이 덧셈만 한다.

    python -m checker.plugin <request.json 경로>
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from . import check_events, load_profile, ProfileError
from .fixes import apply_fixes
from .korean import CorrectorUnavailable, load_backend, run_korean_pass
from .model import Event
from .parsers import parse_text
from .writers import to_srt

API_VERSION = 1
SETTINGS_VERSION = 1

DEFAULT_SETTINGS = {
    "platform": "netflix",
    "language": "ko",
    "kind": "translation",
    "children": False,
    "applyFixes": True,
    "korean": False,
    "kscPath": "",
    "spacing": "principle",
}


def _load_settings(request: dict) -> dict:
    """설정은 SE가 왕복시켜 주는 값 > 플러그인 전용 폴더의 config.json > 기본값 순.

    `config.json`을 함께 보는 이유는 사용자가 손으로 고칠 수 있어야 하기 때문이다 —
    플러그인이 자기 창을 갖기 전까지는 그것이 유일한 설정 수단이다.
    """
    settings = dict(DEFAULT_SETTINGS)

    data_dir = request.get("pluginDataDirectory")
    if data_dir:
        config_path = Path(data_dir) / "config.json"
        if config_path.is_file():
            try:
                settings.update(json.loads(config_path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass  # 손으로 고치다 깨졌더라도 검사는 돌아가야 한다

    stored = request.get("settings")
    if isinstance(stored, dict):
        settings.update(stored)
    return settings


def _report_text(report: dict, settings: dict) -> str:
    profile_name = f"{settings['platform']} {settings['language']} {settings['kind']}"
    lines = [f"프로파일: {profile_name}", ""]
    for v in report["violations"]:
        where = f"#{v['event_index']}"
        if v["line_no"]:
            where += f" {v['line_no']}행"
        mark = "자동" if v["auto_fixable"] else "확인"
        origin = "" if v.get("source", "rule") == "rule" else f" ({v['source']})"
        lines.append(f"[{mark}] {where} {v['rule_id']} {v['clause']}{origin}")
        if v.get("text"):
            lines.append(f"    | {v['text']}")
        lines.append(f"    {v['message']}")
        if v["detail"]:
            lines.append(f"    {v['detail'] if v['detail'].startswith('->') else '-> ' + v['detail']}")
    if not report["violations"]:
        lines.append("위반 없음")
    lines.append("")
    lines.append(f"위반 {len(report['violations'])}건")
    if report.get("unimplemented_checks"):
        lines.append("미구현 검사: " + ", ".join(report["unimplemented_checks"]))
    return "\n".join(lines)


def _summary(report: dict, settings: dict, fixed_count: int, report_path: Path | None) -> str:
    violations = report["violations"]
    auto = sum(1 for v in violations if v["auto_fixable"])
    parts = [
        f"{settings['platform']} {settings['language']} {settings['kind']} 기준 위반 {len(violations)}건"
        f" (자동 교정 가능 {auto}건, 확인 필요 {len(violations) - auto}건)"
    ]
    if settings.get("applyFixes"):
        parts.append(f"자막 {fixed_count}줄을 고쳤습니다." if fixed_count else "고칠 것은 없었습니다.")
    else:
        parts.append("자동 교정은 꺼져 있습니다(applyFixes=false).")
    if report_path:
        parts.append(f"전체 리포트: {report_path}")
    return " ".join(parts)


def run(request: dict) -> dict:
    settings = _load_settings(request)

    subtitle = request.get("subtitle") or {}
    srt_text = subtitle.get("subRip") or ""
    if not srt_text.strip():
        return {"status": "error", "message": "자막이 비어 있습니다."}

    events = parse_text(srt_text)
    if not events:
        return {"status": "error", "message": "자막을 읽지 못했습니다."}

    try:
        profile = load_profile(settings["platform"], settings["language"], settings["kind"])
    except ProfileError as e:
        return {"status": "error", "message": f"프로파일 오류: {e}"}

    report = check_events(
        [e.__dict__ for e in events], profile, children=bool(settings.get("children"))
    )

    notes: list[str] = []
    ko_fixed = None
    if settings.get("korean"):
        try:
            backend = load_backend(settings.get("kscPath") or None)
            ko_fixed, ko_violations = run_korean_pass(
                events, backend, spacing_mode=settings.get("spacing", "principle")
            )
        except CorrectorUnavailable as e:
            # 못 돌렸다는 사실을 사용자에게 알린다. 통과로 보이면 안 된다.
            notes.append(f"한국어 교정 레인 건너뜀: {e}")
        else:
            report["violations"].extend(v.to_dict() for v in ko_violations)
            report["violations"].sort(key=lambda v: (v["event_index"], v["rule_id"]))

    fixed_events = events
    fixed_count = 0
    if settings.get("applyFixes"):
        base = ko_fixed if ko_fixed is not None else events
        fixed_events, _applied, _unfixable = apply_fixes(base, profile)
        fixed_count = sum(1 for a, b in zip(events, fixed_events) if a.text != b.text)

    report_path = None
    data_dir = request.get("pluginDataDirectory") or request.get("tempDirectory")
    if data_dir:
        # SE는 message 한 덩어리만 보여준다. 조항까지 붙은 전체 리포트는 파일로 남긴다.
        report_path = Path(data_dir) / "last-report.txt"
        try:
            report_path.write_text(_report_text(report, settings), encoding="utf-8")
        except OSError:
            report_path = None

    message = _summary(report, settings, fixed_count, report_path)
    if notes:
        message += " / " + " / ".join(notes)

    response = {
        "status": "ok",
        "message": message,
        "settings": settings,
        "settingsVersion": SETTINGS_VERSION,
        "undoDescription": "자막 규정 검사",
    }
    if settings.get("applyFixes") and fixed_count:
        response["subtitle"] = {"format": "SubRip", "native": to_srt(fixed_events)}
    return response


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("사용법: python -m checker.plugin <request.json>", file=sys.stderr)
        return 2

    request_path = Path(argv[0])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"요청 파일을 읽지 못했습니다: {e}", file=sys.stderr)
        return 2

    response_path = Path(request.get("responseFilePath") or "")
    try:
        response = run(request)
    except Exception:  # 어떤 예외도 SE에 "오류"로 전달하고 자막은 건드리지 않는다
        response = {
            "status": "error",
            "message": "플러그인 내부 오류:\n" + traceback.format_exc(limit=3),
        }

    response.setdefault("apiVersion", API_VERSION)
    if not response_path.name:
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0
    response_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
