"""자막 파일 -> 이벤트 배열. 지금은 SRT와 WebVTT만 다룬다.

포맷 지원을 늘리는 것은 이 도구의 목적이 아니다 — libse가 300개 넘게 갖고 있고
한국어 교정기에도 vtt/smi/ass/ttml 파서가 있다. 여기서는 검사에 필요한 최소만
읽고, 넓은 포맷 지원은 편집기 본체가 붙을 때 그쪽에 맡긴다.
"""

from __future__ import annotations

import re
from pathlib import Path

from .model import Event

_TIME = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
TIMELINE_RE = re.compile(rf"{_TIME}\s*-->\s*{_TIME}")


def _to_ms(h: str, m: str, s: str, frac: str) -> int:
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(frac.ljust(3, "0"))


def parse(path: Path) -> list[Event]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n")
    events: list[Event] = []
    index = 0

    for block in re.split(r"\n{2,}", raw):
        lines = [l for l in block.split("\n") if l.strip() != ""]
        if not lines:
            continue
        timeline_at = next((i for i, l in enumerate(lines) if TIMELINE_RE.search(l)), None)
        if timeline_at is None:
            continue  # WEBVTT 헤더, NOTE, 스타일 블록 등
        m = TIMELINE_RE.search(lines[timeline_at])
        text = "\n".join(lines[timeline_at + 1 :]).strip()
        if not text:
            continue
        index += 1
        events.append(
            Event(
                index=index,
                start_ms=_to_ms(*m.groups()[:4]),
                end_ms=_to_ms(*m.groups()[4:]),
                text=text,
            )
        )
    return events
