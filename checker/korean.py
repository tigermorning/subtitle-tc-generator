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


def load_backend(corrector_path: str | None = None):
    """교정기를 불러온다.

    경로는 인자 > 환경변수 `KSC_PATH` 순으로 찾는다. 교정기를 이 저장소의
    의존성으로 박지 않는 이유는 두 프로젝트가 별개이기 때문이다 — 교정기는
    일반 사용자용 범용 도구로 남고, 편집기가 그것을 빌려 쓴다.

    반환: fn(texts, spacing_mode) -> (corrected_texts, flags)
      flags 는 {"line_index": int, "original_text": str,
                "suggested_fix": str, "reason": str} 목록
    """
    root = corrector_path or os.environ.get("KSC_PATH")
    if not root:
        raise CorrectorUnavailable(
            "교정기 경로를 모릅니다. KSC_PATH 환경변수나 --ksc-path로 지정하세요."
        )
    root_path = Path(root).expanduser().resolve()
    if not (root_path / "subtitle_corrector").is_dir():
        raise CorrectorUnavailable(f"교정기가 없습니다: {root_path}")

    if str(root_path) not in sys.path:
        sys.path.insert(0, str(root_path))
    try:
        from subtitle_corrector.engine.pipeline import correct_entries  # type: ignore
        from subtitle_corrector.parsers import SubtitleEntry  # type: ignore
    except ImportError as e:  # kiwipiepy 등 의존성이 없을 때
        raise CorrectorUnavailable(f"교정기를 불러오지 못했습니다: {e}") from e

    def backend(texts: list[str], spacing_mode: str = "principle"):
        # 문서 전체를 한 번에 넘긴다 — 용어 일관성·존댓말 검사가 문서 단위이기 때문이다.
        entries = [
            SubtitleEntry(index=i + 1, start="", end="", text=t) for i, t in enumerate(texts)
        ]
        fixed, flags, _notes = correct_entries(
            entries, doc_type="subtitle", spacing_mode=spacing_mode
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
) -> tuple[list[Event], list[Violation]]:
    """대사만 교정기에 넘기고, 바뀐 것과 플래그를 위반으로 돌려준다.

    자동 교정 결과도 파일에 바로 반영하지 않고 `auto_fixable` 위반으로 보고한다 —
    무엇이 바뀌는지 사람이 보고 정하는 것이 이 도구의 방식이다.
    """
    texts, slots = extract_dialogue(events)
    if not texts:
        return events, []

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
                    detail=f"{before.strip()!r} -> {after.strip()!r}",
                    auto_fixable=True,
                    source="corrector",
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
            )
        )

    rebuilt = rebuild(events, corrected, slots)
    return rebuilt, violations
