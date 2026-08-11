"""자막을 화면 어디에 놓을지 정한다.

**SDH든 번역이든 똑같이 적용되는 규칙이다.** 화면에 이미 글자가 있는 자리에
자막을 얹으면 둘 다 못 읽는다. 그러면 말자막을 **상단 중앙**으로 올린다.

    화면 아래에 글자가 있다        -> 말자막을 위로
    그 구간이 끝났다               -> 다시 아래로 (계속 위에 두지 않는다)

"화면에 글자가 있다"는 두 가지로 안다.

    ① 자막 파일 안에서   같은 시간대에 화면자막(번인 텍스트를 옮긴 자막)이 있다
    ② 영상 자체에서      화면 아래쪽에 글자가 타 있다(번인 자막·자막 없는 표지판)

①은 확실하다. 파일에 다 들어 있으니 기계가 판단하고 고칠 수 있다.
②는 추정이다. 영상 아래쪽의 **윤곽선 밀도**를 재서 평소보다 튀는 구간을 찾는데,
글자가 아니라 무늬나 조명일 수도 있다. 그래서 ②는 **고치지 않고 알리기만** 한다.

위치 태그는 `{\\an8}`(상단 중앙)을 쓴다. SubtitleEdit도, ASS/SSA도, 대부분의
플레이어도 이 표기를 읽는다. TTML로 내보낼 때는 `region`으로 바뀐다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Event

TOP_TAG = "{\\an8}"
# 위치 태그는 여러 꼴로 들어온다. 우리 것만 알면 남이 만든 자막에서 못 알아본다.
POSITION_TAG = re.compile(r"\{\\an?([1-9])\}")
BOTTOM_CODES = {"1", "2", "3"}
TOP_CODES = {"7", "8", "9"}


@dataclass
class PositionSuggestion:
    event_index: int
    to_top: bool
    reason: str
    certain: bool          # False면 사람이 봐야 한다 — 영상 추정이라 틀릴 수 있다


def position_of(text: str) -> str | None:
    """자막에 붙은 위치 코드. 없으면 None(= 기본 하단)."""
    found = POSITION_TAG.search(text)
    return found.group(1) if found else None


def is_top(text: str) -> bool:
    return position_of(text) in TOP_CODES


def strip_position(text: str) -> str:
    return POSITION_TAG.sub("", text).lstrip()


def set_top(text: str, top: bool = True) -> str:
    """위치 태그를 갈아 끼운다. 태그는 **자막 맨 앞**에 하나만 둔다."""
    body = strip_position(text)
    return f"{TOP_TAG}{body}" if top else body


def is_forced_narrative(text: str, profile: dict | None = None) -> bool:
    """화면자막(번인 텍스트를 옮긴 자막)인지.

    플랫폼마다 표기가 다르다. 넷플릭스 한국어는 큰따옴표, 다른 곳은 이탤릭이나
    대괄호를 쓴다. **확실한 것만 화면자막으로 본다** — 대사를 화면자막으로 잘못
    보면 멀쩡한 자막을 위로 올려 버린다.
    """
    body = strip_position(text).strip()
    if not body:
        return False

    quote_style = ((profile or {}).get("forced_narrative") or {}).get("quote_style")
    if quote_style == "double" and body.startswith("“") and body.endswith("”"):
        return True
    if body.startswith('"') and body.endswith('"') and len(body) > 2:
        return True
    # 이탤릭으로 통째로 감싼 것도 흔한 표기다. 일부만 기울인 것은 강조라 제외한다.
    if re.fullmatch(r"<i>[^<]*</i>", body, re.IGNORECASE | re.DOTALL):
        return True
    return False


def overlaps(a: Event, b: Event) -> bool:
    return a.start_ms < b.end_ms and b.start_ms < a.end_ms


def suggest_positions(events: list[Event], profile: dict | None = None,
                      busy_spans: list[tuple[int, int]] | None = None
                      ) -> list[PositionSuggestion]:
    """올려야 할 자막과 내려야 할 자막을 찾는다.

    `busy_spans`는 영상 아래쪽에 글자가 있는 것으로 **추정되는** 구간이다
    (`media.detect_bottom_text`). 없으면 파일 안의 근거만 쓴다.
    """
    out: list[PositionSuggestion] = []
    narratives = [e for e in events if is_forced_narrative(e.text, profile)]

    for event in events:
        if event in narratives:
            continue   # 화면자막 자신은 원래 자리(번인 글자 옆)에 둔다

        collide = next((n for n in narratives if overlaps(event, n)), None)
        busy = None
        if not collide and busy_spans:
            busy = next(((s, e) for s, e in busy_spans
                         if s < event.end_ms and event.start_ms < e), None)

        if collide:
            if not is_top(event.text):
                out.append(PositionSuggestion(
                    event.index, True,
                    f"화면자막({collide.index}번)과 겹칩니다 — 말자막을 상단 중앙으로", True))
        elif busy:
            if not is_top(event.text):
                out.append(PositionSuggestion(
                    event.index, True,
                    "영상 아래쪽에 글자가 있어 보입니다 — 확인 후 상단으로 올리세요", False))
        elif is_top(event.text):
            # 겹칠 것이 없는데 위에 있다. 앞 자막을 올린 뒤 되돌리지 않은 자국이다.
            out.append(PositionSuggestion(
                event.index, False,
                "겹치는 화면자막이 없습니다 — 하단으로 되돌립니다", True))

    return out


def apply_positions(events: list[Event], suggestions: list[PositionSuggestion],
                    only_certain: bool = True) -> int:
    """제안을 자막에 반영한다. 몇 개를 고쳤는지 돌려준다.

    영상 추정(`certain=False`)은 기본적으로 손대지 않는다. 무늬를 글자로 잘못 본
    것일 수 있고, 그 상태로 올려 버리면 사람이 원인을 못 찾는다.
    """
    by_index = {e.index: e for e in events}
    changed = 0
    for suggestion in suggestions:
        if only_certain and not suggestion.certain:
            continue
        event = by_index.get(suggestion.event_index)
        if event is None:
            continue
        new_text = set_top(event.text, suggestion.to_top)
        if new_text != event.text:
            event.text = new_text
            changed += 1
    return changed
