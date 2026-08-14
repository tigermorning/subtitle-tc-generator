"""한국어 교정 레인 — 한국어 교정기(korean-subtitle-corrector)를 붙인다.

**경계**: 교정기는 자막을 몰라야 한다. 화자 표시 `[진수]`, 효과음 `[문 닫는 소리]`,
음표 `♪`, 2인 화자 하이픈, 서식 태그는 자막 문법이지 한국어가 아니다. 그대로
넘기면 교정기가 그것들을 문장으로 읽고 엉뚱한 띄어쓰기·맞춤법 제안을 낸다.

그래서 이 모듈이 **자막 문법을 벗겨 내고 대사만** 넘긴 뒤 결과를 제자리에
되돌린다. 자막 지식은 편집기가, 한국어 지식은 교정기가 갖는다는 분리 원칙이
코드로 나타나는 자리다.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from .model import Event, Violation

# 자막 문법 조각. 교정기에 넘기지 않는다.
MARKUP_RE = re.compile(
    r"""
    \[[^\]]*\]        # 화자 표시 · 효과음
  | ♪                 # 음표
  | \{\\[^}]*\}       # ASS 태그
  | <[^>]+>           # HTML 태그
    """,
    re.VERBOSE,
)
LEADING_DASH_RE = re.compile(r"^\s*-\s*")


class CorrectorUnavailable(Exception):
    """교정기를 못 찾았거나 의존성이 없다. 검사를 건너뛰되 조용히 넘기지 않는다."""


def split_chunks(line: str) -> list[tuple[str, str]]:
    """한 줄을 (종류, 텍스트) 조각으로 가른다. 종류는 markup 또는 dialogue."""
    chunks: list[tuple[str, str]] = []

    dash = LEADING_DASH_RE.match(line)
    rest = line
    if dash:
        chunks.append(("markup", dash.group(0)))
        rest = line[dash.end() :]

    pos = 0
    for m in MARKUP_RE.finditer(rest):
        if m.start() > pos:
            chunks.append(("dialogue", rest[pos : m.start()]))
        chunks.append(("markup", m.group(0)))
        pos = m.end()
    if pos < len(rest):
        chunks.append(("dialogue", rest[pos:]))
    return chunks


def extract_dialogue(events: list[Event]) -> tuple[list[str], list[tuple[int, int, int]]]:
    """대사 조각만 뽑는다.

    반환: (대사 목록, 위치 목록). 위치는 (event_index, line_no, chunk_no)로,
    교정 결과를 원래 자리에 되돌릴 때 쓴다.
    """
    texts: list[str] = []
    slots: list[tuple[int, int, int]] = []
    for ev in events:
        for line_no, line in enumerate(ev.lines, 1):
            for chunk_no, (kind, text) in enumerate(split_chunks(line)):
                if kind == "dialogue" and text.strip():
                    texts.append(text)
                    slots.append((ev.index, line_no, chunk_no))
    return texts, slots


def rebuild(events: list[Event], corrected: list[str], slots) -> list[Event]:
    """교정된 대사를 자막 문법 사이 제자리에 되돌린다."""
    replacement = {slot: text for slot, text in zip(slots, corrected)}
    out: list[Event] = []
    for ev in events:
        new_lines = []
        for line_no, line in enumerate(ev.lines, 1):
            parts = []
            for chunk_no, (kind, text) in enumerate(split_chunks(line)):
                parts.append(replacement.get((ev.index, line_no, chunk_no), text))
            new_lines.append("".join(parts))
        out.append(Event(ev.index, ev.start_ms, ev.end_ms, "\n".join(new_lines)))
    return out


def _corrector_options(root_path, profile: dict | None) -> dict:
    """플랫폼 표기를 교정기에 넘길 값으로 옮긴다.

    **교정기는 이미 이것들을 받을 줄 안다**(`markers`, `style`). 우리가 안 넘기고
    있었을 뿐이다(사용자 지적 2026-08-11). 안 넘기면 교정기는 기본값 `[]`로 보고,
    쿠팡처럼 `(화자명)`을 쓰는 작업에서 화자 표시를 대사로 읽는다 — 조사·어미
    규칙이 화자명에 걸려 엉뚱한 교정이 나온다.

    OTT마다 다른 것은 프로파일이 알고, 한국어 규범은 교정기가 안다. 각자 아는 것을
    주고받는 자리가 여기다.
    """
    if not profile:
        return {}
    try:
        from subtitle_corrector.engine.options import (  # type: ignore
            SubtitleMarkers, normalize_punctuation_style)
    except ImportError:
        return {}

    speaker = ((profile.get("speaker_id") or {}).get("enclosure") or "[]")
    # **어조 부호는 화자명과 같다고 가정하면 안 된다.** 쿠팡은 화자명이 소괄호인데
    # 어조·효과음은 대괄호다: `(철수) [작게]`. 같다고 넘기면 교정기가 대괄호 어조를
    # 대사로 읽는다(사용자 지적 2026-08-11).
    tone = ((profile.get("tone") or {}).get("enclosure")
            or (profile.get("sound_effect") or {}).get("enclosure")
            or speaker)
    text_rules = profile.get("text") or {}
    # 말줄임표: 프로파일이 정한 글자를 교정기 용어로 옮긴다. 정하지 않은 작업물
    # (디즈니처럼 둘 다 되는 곳)은 건드리지 않는다.
    ellipsis = {"…": "char", "...": "dots"}.get(text_rules.get("ellipsis_char"))

    options = {"markers": SubtitleMarkers(speaker=speaker, tone=tone)}
    if ellipsis:
        options["style"] = normalize_punctuation_style(ellipsis_style=ellipsis)
    return options


def find_corrector(explicit: str | None = None) -> Path | None:
    """한국어 교정기를 찾는다.

    **환경변수를 손으로 넣게 하지 않는다.** 옆에 있으면 그냥 쓴다 — ffmpeg·모델을
    찾는 방식과 같다. 사람이 설정을 만들어야 도는 구조는 결국 안 쓰인다.
    """
    from .paths import user_data

    # **사람이 콕 집어 준 자리는 그것만 본다.** 틀렸으면 다른 것을 몰래 쓰지 않고
    # 없다고 한다 — 쓰는 사람은 자기가 지정한 것이 도는 줄 안다.
    named = explicit or os.environ.get("KSC_PATH")
    if named:
        path = Path(named)
        return path if (path / "subtitle_corrector").is_dir() else None

    candidates = []
    here = Path(__file__).resolve().parent.parent
    beside_exe = Path(sys.executable).resolve().parent
    for base in (here.parent, beside_exe.parent, beside_exe,
                 Path.home() / "Documents", user_data()):
        candidates.append(base / "korean-subtitle-corrector")

    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if (path / "subtitle_corrector").is_dir():
            return path
    return None


def corrector_info(explicit: str | None = None) -> dict:
    """붙어 있는 교정기가 **무엇이고 계약이 맞는지** 말한다.

    두 저장소는 라이브러리로 물려 있다. 교정기가 함수 이름이나 반환 모양을 바꾸면
    이쪽이 깨지는데, **그 사고는 실사용 중에야 드러난다** — 우리 시험은 가짜 백엔드로
    돌기 때문이다(그래야 kiwipiepy 310MB와 API 키 없이 돈다).

    그래서 계약을 여기서 다시 정의하지 않고 **교정기가 스스로 들고 있는 검사기를
    실행한다**(`tools/check_public_api.py`). 계약이 한 곳에만 있어야 두 벌이 갈라지지
    않는다. 교정기가 그 파일을 갖고 있지 않으면(옛 판) 그 사실을 그대로 말한다.

    반환: {found, path, commit, contract, detail}
      contract — "ok" | "broken" | "unknown"(검사기 없음) | "no-corrector"
    """
    import subprocess

    found = find_corrector(explicit)
    if not found:
        return {"found": False, "path": None, "commit": None,
                "contract": "no-corrector", "detail": "교정기를 찾지 못했습니다."}

    root = found.expanduser().resolve()
    info = {"found": True, "path": str(root), "commit": None,
            "contract": "unknown", "detail": ""}

    try:  # 어느 판이 붙어 있는지. 실패해도 검사는 계속한다.
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            info["commit"] = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass

    checker_script = root / "tools" / "check_public_api.py"
    if not checker_script.is_file():
        info["detail"] = ("교정기에 tools/check_public_api.py가 없습니다 — "
                          "계약을 확인하지 못했습니다.")
        return info

    try:
        out = subprocess.run([sys.executable, str(checker_script)],
                             capture_output=True, text=True, timeout=60, cwd=str(root))
    except (OSError, subprocess.SubprocessError) as e:
        info["detail"] = f"계약 검사를 돌리지 못했습니다: {e}"
        return info

    info["contract"] = "ok" if out.returncode == 0 else "broken"
    info["detail"] = (out.stdout or out.stderr).strip()
    return info


def _load_corrector_env(root_path: Path) -> None:
    """교정기의 `.env`를 읽어 환경에 올린다.

    **조용히 죽던 자리다.** 교정기는 `load_dotenv()`를 인자 없이 부르는데, 그러면
    **현재 작업 폴더**에서 `.env`를 찾는다. 편집기에서 부르면 작업 폴더가 편집기
    쪽이라 교정기의 키를 못 찾고, 사전 조회가 통째로 실패한다. 사전이 없으면
    교정기 가드가 "근거 없음"으로 넘어가므로 **오류처럼 보이지도 않는다** — 검사가
    조용히 헐거워진다(2026-08-11 발견).

    이미 환경에 있는 값은 덮지 않는다. 사용자가 일부러 넣은 값이 이길 자리다.
    """
    env_file = root_path / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_backend(corrector_path: str | None = None):
    """교정기를 불러온다.

    경로는 인자 > 환경변수 `KSC_PATH` 순으로 찾는다. 교정기를 이 저장소의
    의존성으로 박지 않는 이유는 두 프로젝트가 별개이기 때문이다 — 교정기는
    일반 사용자용 범용 도구로 남고, 편집기가 그것을 빌려 쓴다.

    반환: fn(texts, spacing_mode) -> (corrected_texts, flags)
      flags 는 {"line_index": int, "original_text": str,
                "suggested_fix": str, "reason": str} 목록
    """
    found = find_corrector(corrector_path)
    if not found:
        raise CorrectorUnavailable(
            "교정기를 찾지 못했습니다. 편집기 폴더 옆에 두거나 KSC_PATH로 알려 주세요."
        )
    root_path = found.expanduser().resolve()
    if not (root_path / "subtitle_corrector").is_dir():
        raise CorrectorUnavailable(f"교정기가 없습니다: {root_path}")

    _load_corrector_env(root_path)

    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))
    try:
        from subtitle_corrector.engine.pipeline import correct_entries  # type: ignore
        from subtitle_corrector.parsers import SubtitleEntry  # type: ignore
    except ImportError as e:  # kiwipiepy 등 의존성이 없을 때
        raise CorrectorUnavailable(f"교정기를 불러오지 못했습니다: {e}") from e

    def backend(texts: list[str], spacing_mode: str = "principle", profile: dict | None = None):
        # 문서 전체를 한 번에 넘긴다 — 용어 일관성·존댓말 검사가 문서 단위이기 때문이다.
        entries = [
            SubtitleEntry(index=i + 1, start="", end="", text=t) for i, t in enumerate(texts)
        ]
        fixed, flags, _notes = correct_entries(
            entries, doc_type="subtitle", spacing_mode=spacing_mode,
            **_corrector_options(root_path, profile)
        )
        return (
            [e.text for e in fixed],
            [
                {
                    "line_index": f.line_index,
                    "original_text": f.original_text,
                    "suggested_fix": f.suggested_fix,
                    "reason": f.reason,
                }
                for f in flags
            ],
        )

    return backend


def run_korean_pass(
    events: list[Event],
    backend,
    spacing_mode: str = "principle",
    profile: dict | None = None,
) -> tuple[list[Event], list[Violation]]:
    """대사만 교정기에 넘기고, 바뀐 것과 플래그를 위반으로 돌려준다.

    자동 교정 결과도 파일에 바로 반영하지 않고 `auto_fixable` 위반으로 보고한다 —
    무엇이 바뀌는지 사람이 보고 정하는 것이 이 도구의 방식이다.
    """
    texts, slots = extract_dialogue(events)
    if not texts:
        return events, []

    try:
        corrected, flags = backend(texts, spacing_mode, profile)
    except TypeError:
        # 오래된 백엔드(프로파일을 모르는 것)와도 계속 돌아간다.
        corrected, flags = backend(texts, spacing_mode)
    if len(corrected) != len(texts):
        raise CorrectorUnavailable("교정기가 돌려준 줄 수가 입력과 다릅니다")

    violations: list[Violation] = []

    for (event_index, line_no, _chunk), before, after in zip(slots, texts, corrected):
        if before != after:
            violations.append(
                Violation(
                    rule_id="K01",
                    clause="한글 맞춤법 · 표준어 규정",
                    event_index=event_index,
                    line_no=line_no,
                    message="한국어 교정 제안",
                    detail=f"-> {after.strip()}",
                    auto_fixable=True,
                    source="corrector",
                    text=before.strip(),
                )
            )

    for flag in flags:
        slot_no = flag["line_index"] - 1
        if not 0 <= slot_no < len(slots):
            continue
        event_index, line_no, _chunk = slots[slot_no]
        detail = flag["reason"]
        if flag.get("suggested_fix"):
            detail = f"{flag['suggested_fix']!r} — {detail}"
        violations.append(
            Violation(
                rule_id="K02",
                clause="한글 맞춤법 · 표준어 규정",
                event_index=event_index,
                line_no=line_no,
                message="한국어 확인 필요",
                detail=detail,
                auto_fixable=False,
                source="corrector",
                text=flag.get("original_text", "").strip(),
            )
        )

    rebuilt = rebuild(events, corrected, slots)
    return rebuilt, violations
