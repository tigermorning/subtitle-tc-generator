"""자막을 나누고 합치고 다듬는 조작.

**화면에서 떼어 놓는다.** 여기 있는 함수들은 Qt를 모르고 자막 목록만 다룬다 —
그래야 시험할 수 있고, 나중에 명령줄에서도 쓸 수 있다.

조작은 작업자가 SE에서 쓰던 것을 그대로 옮겼다(작업자 자료의 단축키 목록).

    Ctrl+Space        자막 분리        재생 위치에서 자른다
    Alt+Space         독백 병합        다음 자막과 합친다
    Alt+Shift+Space   대화 병합        합치되 하이픈을 넣는다
    Ctrl+-            대화 대시        하이픈을 넣고 뺀다
    Ctrl+\\            줄바꿈 제거
    Alt+Up / Alt+Down 위치 {\\an8} / 기본

**스포팅에서는 원문이 예쁘게 나뉠 필요가 없다**(작업자 자료). 그래서 분리는 글자
기준이 아니라 **시간 기준**이다 — 재생 위치에서 자르고 글자는 비율로 나눈다.
"""

from __future__ import annotations

from checker.model import Event
from checker.position import PLACES, position_of, set_place, strip_position

DASH = "- "
MIN_PIECE_MS = 100


def _renumber(events: list[Event]) -> list[Event]:
    for i, event in enumerate(events, 1):
        event.index = i
    return events


def split_at(events: list[Event], index: int, at_ms: int) -> tuple[list[Event], int]:
    """자막 하나를 재생 위치에서 둘로 나눈다. (새 목록, 새로 생긴 자막 번호).

    글자는 시간 비율로 나눈다. 정확히 맞을 리 없지만 **스포팅 단계에서는 글자가
    예쁘게 나뉠 필요가 없다** — 사람이 뒤에서 고친다.
    """
    for position, event in enumerate(events):
        if event.index != index:
            continue
        if not (event.start_ms + MIN_PIECE_MS <= at_ms <= event.end_ms - MIN_PIECE_MS):
            return events, index          # 너무 가장자리다. 나누지 않는다

        ratio = (at_ms - event.start_ms) / max(event.end_ms - event.start_ms, 1)
        text = strip_position(event.text)
        cut = max(1, min(len(text) - 1, round(len(text) * ratio)))
        # 낱말 가운데를 자르지 않는다. 가까운 빈칸을 찾는다.
        space = text.rfind(" ", 0, cut + 1)
        if space > 0:
            cut = space
        tag = f"{{\\an{position_of(event.text)}}}" if position_of(event.text) else ""

        first = Event(event.index, event.start_ms, at_ms, tag + text[:cut].strip())
        second = Event(event.index + 1, at_ms, event.end_ms, tag + text[cut:].strip())
        events = events[:position] + [first, second] + events[position + 1:]
        return _renumber(events), first.index + 1
    return events, index


def merge_with_next(events: list[Event], index: int, dialogue: bool = False
                    ) -> tuple[list[Event], int]:
    """다음 자막과 합친다. `dialogue`면 두 사람 대화로 보고 하이픈을 넣는다."""
    for position, event in enumerate(events):
        if event.index != index or position + 1 >= len(events):
            continue
        following = events[position + 1]
        first, second = strip_position(event.text), strip_position(following.text)
        if dialogue:
            first = first if first.startswith(DASH.strip()) else DASH + first
            second = second if second.startswith(DASH.strip()) else DASH + second
            text = f"{first}\n{second}"
        else:
            # 독백은 한 사람의 말이 이어지는 것이다. 줄만 바꾼다.
            text = f"{first}\n{second}"
        tag = f"{{\\an{position_of(event.text)}}}" if position_of(event.text) else ""
        merged = Event(event.index, event.start_ms, following.end_ms, tag + text)
        events = events[:position] + [merged] + events[position + 2:]
        return _renumber(events), merged.index
    return events, index


def toggle_dash(event: Event) -> str:
    """대화 하이픈을 넣고 뺀다. 줄마다 앞에 `- `를 붙이거나 뗀다."""
    lines = strip_position(event.text).split("\n")
    tag = f"{{\\an{position_of(event.text)}}}" if position_of(event.text) else ""
    if all(line.lstrip().startswith("-") for line in lines if line.strip()):
        lines = [line.lstrip().lstrip("-").lstrip() for line in lines]
    else:
        lines = [DASH + line.lstrip() if line.strip() else line for line in lines]
    return tag + "\n".join(lines)


def remove_line_breaks(event: Event) -> str:
    """줄바꿈을 없앤다. 한 줄로 붙여 놓고 다시 나누는 것이 빠를 때가 있다."""
    tag = f"{{\\an{position_of(event.text)}}}" if position_of(event.text) else ""
    return tag + " ".join(part.strip() for part in
                          strip_position(event.text).split("\n") if part.strip())


def set_position(event: Event, place: str) -> str:
    """`top_center` 같은 이름으로 자리를 옮긴다. `default`면 태그를 뗀다."""
    return set_place(event.text, PLACES.get(place, ""))


def set_in_point(events: list[Event], index: int, at_ms: int) -> bool:
    """인점을 지금 위치로. 앞 자막을 침범하거나 자막이 뒤집히면 하지 않는다."""
    for position, event in enumerate(events):
        if event.index != index:
            continue
        floor = events[position - 1].end_ms if position else 0
        if not (floor <= at_ms < event.end_ms - MIN_PIECE_MS):
            return False
        event.start_ms = at_ms
        return True
    return False


def set_out_point(events: list[Event], index: int, at_ms: int) -> bool:
    """아웃점을 지금 위치로. 다음 자막을 침범하면 하지 않는다."""
    for position, event in enumerate(events):
        if event.index != index:
            continue
        ceiling = (events[position + 1].start_ms if position + 1 < len(events)
                   else at_ms + 1)
        if not (event.start_ms + MIN_PIECE_MS < at_ms <= ceiling):
            return False
        event.end_ms = at_ms
        return True
    return False
