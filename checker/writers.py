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
