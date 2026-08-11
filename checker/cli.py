"""명령줄 진입점.

    python -m checker examples/sample.srt --platform netflix --lang ko --kind sdh
    python -m checker file.srt -p netflix -l en -k translation --json
    python -m checker --list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import check_events, available_profiles, load_profile, ProfileError
from .korean import CorrectorUnavailable, load_backend, run_korean_pass
from .parsers import parse


def _format_text(report: dict, path: Path) -> str:
    out = [f"{path.name} — {report['profile']} {report['kind']}"]
    violations = report["violations"]
    if not violations:
        out.append("  위반 없음")
    for v in violations:
        where = f"#{v['event_index']}"
        if v["line_no"]:
            where += f" {v['line_no']}행"
        mark = "자동" if v["auto_fixable"] else "확인"
        origin = "" if v.get("source", "rule") == "rule" else f" ({v['source']})"
        out.append(f"  [{mark}] {where:>10}  {v['rule_id']} {v['clause']}{origin}")
        out.append(f"              {v['message']}")
        if v["detail"]:
            out.append(f"              -> {v['detail']}")

    out.append("")
    out.append(f"  위반 {len(violations)}건")
    if report["unimplemented_checks"]:
        # 검사하지 않은 것을 통과로 보이게 하지 않는다.
        out.append(f"  미구현 검사 {len(report['unimplemented_checks'])}건: "
                   + ", ".join(report["unimplemented_checks"]))
    return "\n".join(out)


def _force_utf8_output() -> None:
    """Windows 콘솔 기본 인코딩(cp949)에서 리포트가 깨지지 않게 한다.

    편집기는 Windows에서 돌아갈 가능성이 높은데, 한국어 규정 문구에는 cp949로
    표현할 수 없는 문자(—, ♪, …)가 들어 있다. 출력이 예외로 죽지 않아야 한다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser(prog="checker", description="플랫폼 규정 준수 검사")
    ap.add_argument("file", nargs="?", type=Path, help="자막 파일 (.srt / .vtt)")
    ap.add_argument("-p", "--platform", default="netflix")
    ap.add_argument("-l", "--lang", default="ko")
    ap.add_argument("-k", "--kind", choices=["sdh", "translation"], default="translation")
    ap.add_argument("--children", action="store_true", help="아동 프로그램 기준 적용")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--list", action="store_true", help="쓸 수 있는 프로파일 목록")
    ap.add_argument("--korean", action="store_true",
                    help="한국어 교정기 레인을 함께 돌린다(맞춤법·띄어쓰기)")
    ap.add_argument("--ksc-path", help="한국어 교정기 저장소 경로(기본: 환경변수 KSC_PATH)")
    ap.add_argument("--spacing", choices=["principle", "allowance"], default="principle",
                    help="보조 용언 띄어쓰기 기준(제47항). 교정기 레인에만 쓴다")
    args = ap.parse_args(argv)

    if args.list:
        for platform, lang, kind in available_profiles():
            print(f"{platform:10} {lang:4} {kind}")
        return 0

    if not args.file:
        ap.error("자막 파일이 필요합니다 (또는 --list)")
    if not args.file.is_file():
        print(f"파일이 없습니다: {args.file}", file=sys.stderr)
        return 2

    try:
        profile = load_profile(args.platform, args.lang, args.kind)
    except ProfileError as e:
        print(f"프로파일 오류: {e}", file=sys.stderr)
        return 2

    events = parse(args.file)
    if not events:
        print(f"자막 이벤트를 읽지 못했습니다: {args.file}", file=sys.stderr)
        return 2

    report = check_events([e.__dict__ for e in events], profile, children=args.children)

    if args.korean:
        if args.lang != "ko":
            print("한국어 교정 레인은 --lang ko 에서만 씁니다.", file=sys.stderr)
            return 2
        try:
            backend = load_backend(args.ksc_path)
            _fixed, ko_violations = run_korean_pass(events, backend, spacing_mode=args.spacing)
        except CorrectorUnavailable as e:
            # 못 돌렸다는 사실을 숨기지 않는다 — 통과로 보이면 안 된다.
            print(f"한국어 교정 레인을 건너뜁니다: {e}", file=sys.stderr)
        else:
            report["violations"].extend(v.to_dict() for v in ko_violations)
            report["violations"].sort(key=lambda v: (v["event_index"], v["rule_id"]))

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_text(report, args.file))

    return 1 if report["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
