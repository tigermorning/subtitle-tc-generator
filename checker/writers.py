"""이벤트 -> 자막 파일. 지금은 SRT만 쓴다.

교정 결과는 항상 새 파일로 나간다. 원본을 덮어쓰지 않는 것은 되돌릴 수 있어야
하기 때문이다 — 자동 교정이 틀렸을 때 원본이 없으면 손해가 회복 불가능하다.
"""

from __future__ import annotations

from pathlib import Path

from .model import Event


def to_timecode(ms: int) -> str:
    ms = max(0, int(ms))
    h, rest = divmod(ms, 3600000)
    m, rest = divmod(rest, 60000)
    s, milli = divmod(rest, 1000)
    return f"{h:02}:{m:02}:{s:02},{milli:03}"


def to_srt(events: list[Event]) -> str:
    blocks = []
    for i, ev in enumerate(events, 1):
        blocks.append(
            f"{i}\n{to_timecode(ev.start_ms)} --> {to_timecode(ev.end_ms)}\n{ev.text}\n"
        )
    return "\n".join(blocks)


def write_srt(events: list[Event], path: Path) -> None:
    path.write_text(to_srt(events), encoding="utf-8")


def to_review_srt(events: list[Event], violations: list[dict],
                  clean_mark: str = "·") -> str:
    """지적을 **자막 파일로** 낸다. SE 번역 모드로 원본 옆에 띄워 보기 위해서다.

    타임코드는 원본과 같게 두고 텍스트만 지적 내용으로 바꾼다. 그러면 SE에서
    `파일 - 원본 자막 열기`로 얹었을 때 그리드에 원문과 지적이 나란히 서고,
    영상을 보면서 그 자리로 바로 갈 수 있다. txt 파일을 따로 열어 자막 번호를
    맞춰 가며 보는 왕복이 없어진다.

    **모든 자막에 대해 한 칸씩 낸다.** 위반이 있는 것만 내면 번호가 어긋나 짝이
    맞지 않는다. 깨끗한 줄은 `clean_mark` 한 글자로 조용히 채운다.
    """
    by_index: dict[int, list[dict]] = {}
    for v in violations:
        by_index.setdefault(v["event_index"], []).append(v)

    lines = []
    for ev in events:
        found = by_index.get(ev.index, [])
        if not found:
            text = clean_mark
        else:
            parts = []
            for v in found:
                where = f"{v['line_no']}행 " if v.get("line_no") else ""
                detail = (v.get("detail") or "").strip()
                detail = detail[:40] + "…" if len(detail) > 40 else detail
                mark = "[자동]" if v.get("auto_fixable") else ""
                parts.append(f"{mark}{v['rule_id']} {where}{detail or v['message'][:30]}")
            text = "\n".join(parts[:4])
            if len(found) > 4:
                text += f"\n… 외 {len(found) - 4}건"
        lines.append(Event(ev.index, ev.start_ms, ev.end_ms, text))
    return to_srt(lines)


def write_review_srt(events: list[Event], violations: list[dict], path: Path) -> None:
    path.write_text(to_review_srt(events, violations), encoding="utf-8")
