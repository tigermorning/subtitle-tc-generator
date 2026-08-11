"""자막을 화면 어디에 놓을지 정한다.

**SDH든 번역이든 겹침을 다루는 규칙이 있다는 점은 같다. 다루는 방법이 다르다.**

작업자 자료(`작업 기본 원칙`)가 둘을 나눠 적어 두었다.

    [영상번역] 673행  하단 1/3에 화면자막이 있으면 말자막을 하단 처리
                      {\an1}좌측하단 {\an2}중앙하단 {\an3}우측하단
    [영상번역] 677행  **말자막이 화면자막보다 우선! 둘이 겹치면 말자막 번역**
    [영상번역] 678행  화면자막 상단·말자막 하단으로 둘 다 따라는 업체도 있음
    [SDH]      쿠팡    overlap_with_dialogue: keep_both_top_position

**그래서 처리 방식을 코드에 못박지 않는다.** 같은 번역 작업이라도 업체마다 다르고,
한 업체 안에서도 작업마다 달라진다. 프로파일이 `ask`로 두면 **작업 시작 전에
사람이 고르고**, 고르지 않았으면 검사하지 않는다 — 추측해서 자막을 옮기면
납품물이 틀어진다.

    move_dialogue   말자막을 다른 자리로 옮긴다(어디로 갈지는 `move_to`)
    dialogue_only   말자막만 남긴다. 화면자막 자막은 만들지 않는다(영상번역 기본)
    keep_both       둘 다 두고 자리만 나눈다(SDH에서 흔함)
    ask             정해지지 않았다. 검사도 교정도 하지 않고 정하라고 말한다

화면자막을 무엇으로 표시하는지도 마찬가지로 작업마다 다르다(`forced_narrative.marker`).
번역 자막의 말자막에는 큰따옴표를 **어떤 경우에도** 쓰지 않으므로(같은 문서 108행)
큰따옴표는 화면자막 표식으로 쓸 수 있는 반면, 다른 작업에서는 이탤릭이나 대괄호를
쓴다.

위치 태그는 `{\anN}`을 쓴다. SubtitleEdit도 ASS/SSA도 대부분의 플레이어도 읽는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Event

# 자료 673행에 나온 자리들. 상단은 7·8·9, 하단은 1·2·3.
PLACES = {
    "top_left": "{\\an7}", "top_center": "{\\an8}", "top_right": "{\\an9}",
    "bottom_left": "{\\an1}", "bottom_center": "{\\an2}", "bottom_right": "{\\an3}",
}
TOP_TAG = PLACES["top_center"]
# 위치 태그는 여러 꼴로 들어온다. 우리 것만 알면 남이 만든 자막에서 못 알아본다.
POSITION_TAG = re.compile(r"\{\\an?([1-9])\}")
BOTTOM_CODES = {"1", "2", "3"}
TOP_CODES = {"7", "8", "9"}


MARKERS = ("double_quote", "italic", "bracket", "none")
POLICIES = ("move_dialogue", "dialogue_only", "keep_both")


@dataclass
class JobRules:
    """이 작업에서 화면자막을 어떻게 다룰지. **작업 시작 전에 정해진다.**"""
    marker: str = "ask"
    policy: str = "ask"
    move_to: str = "top_center"

    @classmethod
    def from_profile(cls, profile: dict | None, overrides: dict | None = None):
        fn = ((profile or {}).get("forced_narrative") or {})
        collision = ((profile or {}).get("collision") or {})
        marker = fn.get("marker")
        # 예전 프로파일은 표식을 quote_style로만 적어 두었다. 그것도 읽어 준다.
        if not marker and fn.get("quote_style") == "double":
            marker = "double_quote"
        rules = cls(marker=marker or "ask",
                    policy=collision.get("policy") or "ask",
                    move_to=collision.get("move_to") or "top_center")
        for key, value in (overrides or {}).items():
            if value:
                setattr(rules, key, value)
        return rules

    @property
    def decided(self) -> bool:
        return self.marker != "ask" and self.policy != "ask"

    def undecided_note(self) -> str | None:
        """정해지지 않았으면 무엇을 정해야 하는지 말한다. 추측하지 않는다."""
        missing = []
        if self.marker == "ask":
            missing.append("화면자막 표식(--fn-marker: %s)" % "|".join(MARKERS))
        if self.policy == "ask":
            missing.append("겹칠 때 처리(--collision: %s)" % "|".join(POLICIES))
        if not missing:
            return None
        return ("작업 시작 전에 정해야 합니다 — " + ", ".join(missing)
                + ". 정해지기 전까지 위치 검사는 하지 않습니다.")

    def target_tag(self) -> str:
        return PLACES.get(self.move_to, TOP_TAG)


@dataclass
class PositionSuggestion:
    event_index: int
    reason: str
    certain: bool              # False면 사람이 봐야 한다 — 영상 추정이라 틀릴 수 있다
    tag: str = ""              # 붙일 위치 태그. ""이면 기본 자리로 되돌린다
    action: str = "move"       # move | reset | review

    @property
    def to_top(self) -> bool:
        return position_of(self.tag) in TOP_CODES


def position_of(text: str) -> str | None:
    """자막에 붙은 위치 코드. 없으면 None(= 기본 하단)."""
    found = POSITION_TAG.search(text)
    return found.group(1) if found else None


def is_top(text: str) -> bool:
    return position_of(text) in TOP_CODES


def is_placed(text: str) -> bool:
    """자리가 지정돼 있는지. 기본 자리(태그 없음)와 구분한다."""
    return position_of(text) is not None


def strip_position(text: str) -> str:
    return POSITION_TAG.sub("", text).lstrip()


def set_place(text: str, tag: str) -> str:
    """위치 태그를 갈아 끼운다. 태그는 **자막 맨 앞**에 하나만 둔다."""
    body = strip_position(text)
    return f"{tag}{body}" if tag else body


def set_top(text: str, top: bool = True) -> str:
    return set_place(text, TOP_TAG if top else "")


def is_forced_narrative(text: str, profile: dict | None = None,
                        rules: JobRules | None = None) -> bool:
    """화면자막(번인 텍스트를 옮긴 자막)인지.

    **작업에서 정한 표식만 인정한다.** 예전에는 큰따옴표·이탤릭을 모두 화면자막으로
    봤는데, 그러면 이탤릭을 강조로 쓰는 작업에서 멀쩡한 대사가 화면자막이 된다.
    표식이 정해지지 않았으면(`ask`) 아무것도 화면자막으로 보지 않는다.
    """
    rules = rules or JobRules.from_profile(profile)
    body = strip_position(text).strip()
    if not body or rules.marker in ("ask", "none"):
        return False

    if rules.marker == "double_quote":
        return ((body.startswith("\u201c") and body.endswith("\u201d"))
                or (body.startswith('"') and body.endswith('"') and len(body) > 2))
    if rules.marker == "italic":
        # 통째로 감싼 것만. 일부만 기울인 것은 강조다.
        return bool(re.fullmatch(r"<i>[^<]*</i>", body, re.IGNORECASE | re.DOTALL))
    if rules.marker == "bracket":
        return bool(re.fullmatch(r"\[[^\]]+\]", body))
    return False


def overlaps(a: Event, b: Event) -> bool:
    return a.start_ms < b.end_ms and b.start_ms < a.end_ms


def suggest_positions(events: list[Event], profile: dict | None = None,
                      busy_spans: list[tuple[int, int]] | None = None,
                      rules: JobRules | None = None) -> list[PositionSuggestion]:
    """옮길 자막과 되돌릴 자막을 찾는다.

    `busy_spans`는 영상 아래쪽에 글자가 있는 것으로 **추정되는** 구간이다
    (`media.detect_bottom_text`). 없으면 파일 안의 근거만 쓴다.

    **작업 기준이 정해지지 않았으면 아무 말도 하지 않는다.** 어디로 옮길지 모르는
    채로 옮기면 납품물이 틀어진다.
    """
    rules = rules or JobRules.from_profile(profile)
    if not rules.decided:
        return []

    out: list[PositionSuggestion] = []
    narratives = [e for e in events if is_forced_narrative(e.text, profile, rules)]
    tag = rules.target_tag()

    for event in events:
        if event in narratives:
            continue   # 화면자막 자신은 원래 자리(번인 글자 옆)에 둔다

        collide = next((n for n in narratives if overlaps(event, n)), None)
        busy = None
        if not collide and busy_spans:
            busy = next(((s, e) for s, e in busy_spans
                         if s < event.end_ms and event.start_ms < e), None)

        if collide:
            if rules.policy == "dialogue_only":
                # 영상번역 기준: 말자막이 화면자막보다 우선이고, 겹치면 말자막만
                # 남긴다(작업 기본 원칙 677행). 자막을 지우는 일이라 사람이 한다.
                out.append(PositionSuggestion(
                    collide.index,
                    f"말자막({event.index}번)과 겹칩니다 — 이 작업 기준에서는 "
                    f"말자막이 우선이라 화면자막을 넣지 않습니다",
                    True, "", "review"))
            elif rules.policy == "move_dialogue" and position_of(event.text) != position_of(tag):
                out.append(PositionSuggestion(
                    event.index,
                    f"화면자막({collide.index}번)과 겹칩니다 — 말자막을 "
                    f"{_place_name(rules.move_to)}으로", True, tag))
            # keep_both는 둘 다 그대로 둔다. 자리 배분은 업체 지정에 따른다.
        elif busy:
            if rules.policy != "keep_both" and not is_placed(event.text):
                out.append(PositionSuggestion(
                    event.index,
                    f"영상 아래쪽에 글자가 있어 보입니다 — 확인 후 "
                    f"{_place_name(rules.move_to)}으로 옮기세요", False, tag))
        elif is_placed(event.text) and rules.policy == "move_dialogue":
            # 겹칠 것이 없는데 자리가 지정돼 있다. 앞 자막을 옮긴 뒤 되돌리지 않은 자국.
            out.append(PositionSuggestion(
                event.index, "겹치는 화면자막이 없습니다 — 기본 자리로 되돌립니다",
                True, "", "reset"))

    return out


def _place_name(key: str) -> str:
    names = {"top_left": "좌측 상단", "top_center": "상단 중앙", "top_right": "우측 상단",
             "bottom_left": "좌측 하단", "bottom_center": "중앙 하단",
             "bottom_right": "우측 하단"}
    return names.get(key, key)


def apply_positions(events: list[Event], suggestions: list[PositionSuggestion],
                    only_certain: bool = True) -> int:
    """제안을 자막에 반영한다. 몇 개를 고쳤는지 돌려준다.

    영상 추정(`certain=False`)은 기본적으로 손대지 않는다. 무늬를 글자로 잘못 본
    것일 수 있고, 그 상태로 옮겨 버리면 사람이 원인을 못 찾는다.

    `review`는 자막을 지우라는 뜻이라 기계가 하지 않는다. 지운 자막은 되돌릴 수 없다.
    """
    by_index = {e.index: e for e in events}
    changed = 0
    for suggestion in suggestions:
        if suggestion.action == "review":
            continue
        if only_certain and not suggestion.certain:
            continue
        event = by_index.get(suggestion.event_index)
        if event is None:
            continue
        new_text = set_place(event.text, suggestion.tag)
        if new_text != event.text:
            event.text = new_text
            changed += 1
    return changed
