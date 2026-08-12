"""말투를 센다 — **확정할 수 있는 것만 세고 나머지는 유보한다.**

작업자 자료 312·889행: "다큐멘터리는 무조건 존댓말. 혼잣말조차 존댓말". 그리고
사용자가 덧붙였다 — 다큐는 **합니다체 위주**이지만 **자연스러움을 위해 가끔 '요'를
쓰는 것은 허용된다.**

그래서 **줄마다 '요'를 잡으면 안 된다.** 허용되는 것을 위반으로 부르는 것이고, 그건
오답이다. 오답 하나가 플래그 열 건보다 비싸다. 대신 문서·화자 단위로 **비율**을 낸다.

**임계값을 정해 두지 않는다.** "가끔"이 몇 퍼센트인지는 완성본 자막으로 재야 알고,
재기 전까지는 숫자만 내고 판정하지 않는다. 근거 없는 임계값은 오답 공장이다.

## 무엇을 확정으로 보나

자막은 문장이 여러 줄에 걸쳐 잘린다. 그래서 줄 끝 글자가 종결어미가 아닐 수 있고,
거기서 오분류가 난다. 이 모듈은 **한국어에서 문장 중간에 올 수 없는 어미만** 센다.

    합니다체   ~ㅂ니다 ~습니다 ~ㅂ니까 ~습니까 ~십시오
    해요체     ~요 ~죠
    유보       그 밖의 모든 것

반말은 세지 않는다. `해야`(문장 중간)와 `뭐야`(반말 종결)를 줄 끝만 보고 가를 수
없다. 반말이 필요한 검사(T17 존댓말·반말 혼용)는 **상대가 누구인지** 알아야 하고,
그건 파일이 증명하지 못한다 — 캐릭터 시트가 있어야 한다.

**다큐 검사는 유보를 타지 않는다.** 합니다체와 해요체 둘 다 확정이므로 그 둘의
비율만으로 계산된다.
"""

from __future__ import annotations

import re

from .model import Event
from .text import strip_tags

# 대괄호·소괄호로 싸인 것은 대사가 아니다(화자명·효과음·화면자막 표식).
_MARKUP = re.compile(r"[\[(][^)\]]*[\])]|\{[^}]*\}|♪+")

# 종결어미 뒤에 올 수 있는 것들. 자막은 마침표를 쓰지 않으므로 남는 것은 물음표·
# 느낌표·말줄임표·따옴표뿐이다.
_TRAILING = re.compile(r"[\s.,!?…\"'’”」』〉》~\-]+$")

# **문장 중간에 올 수 없는 어미만 적는다.** 하나를 늘릴 때마다 오분류 위험이 는다.
#
# 합니다체는 `니다`로만 봐서는 안 된다. `아니다`가 걸린다 — 그건 반말이다. 어간
# 뒤에 붙는 것이 `-ㅂ니다`(모음 어간: 합니다)나 `-습니다`(자음 어간: 먹습니다)이므로,
# **`니다` 바로 앞 음절에 ㅂ받침이 있어야** 합니다체다.
#
#     합니다  -> 합(ㅂ받침) + 니다   O
#     먹습니다 -> 습(ㅂ받침) + 니다   O
#     아니다  -> 아(받침 없음) + 니다  X  (반말)
#     아니까  -> 아(받침 없음) + 니까  X  (연결어미 '알+니까')
FORMAL_TAILS = ("니다", "니까")
FORMAL_PLAIN = ("십시오", "십시다")
POLITE = ("요", "죠")

LEVELS = ("합니다체", "해요체")

_JONG_P = 17            # 한글 음절의 종성 ㅂ


def _ends_p(syllable: str) -> bool:
    """음절이 ㅂ받침으로 끝나는가."""
    if not syllable or not ("가" <= syllable <= "힣"):
        return False
    return (ord(syllable) - 0xAC00) % 28 == _JONG_P


def _tail(text: str) -> str:
    """대사만 남기고 맨 끝을 돌려준다. 대사가 없으면 빈 문자열."""
    body = _MARKUP.sub(" ", strip_tags(text))
    # 여러 줄 자막은 마지막 줄이 문장의 끝이다.
    lines = [ln for ln in body.split("\n") if ln.strip()]
    if not lines:
        return ""
    return _TRAILING.sub("", lines[-1].strip())


def level_of(text: str) -> str | None:
    """자막 한 줄의 말투. **확정할 수 없으면 `None`이다.**

    합니다체를 해요체보다 먼저 본다 — `~합니까요` 같은 것은 없지만, 순서를 정해
    두면 어미를 늘릴 때 규칙이 흔들리지 않는다.
    """
    tail = _tail(text)
    if not tail:
        return None
    if tail.endswith(FORMAL_PLAIN):
        return "합니다체"
    for ending in FORMAL_TAILS:
        if tail.endswith(ending) and _ends_p(tail[: -len(ending)][-1:]):
            return "합니다체"
    if tail.endswith(POLITE):
        return "해요체"
    return None


def summary(events: list[Event]) -> dict:
    """말투 집계. **유보 건수를 함께 낸다** — 숫자가 무엇 위에서 나온 것인지 알아야 한다.

    `formal_ratio`는 **확정된 것들 사이의 비율**이다. 전체 자막 수로 나누면 유보가
    많을 때 비율이 뜻 없이 낮아진다.
    """
    counts = {level: 0 for level in LEVELS}
    undecided: list[int] = []
    for ev in events:
        level = level_of(ev.text)
        if level is None:
            if _tail(ev.text):          # 대사가 있는데 못 가른 것만 센다
                undecided.append(ev.index)
            continue
        counts[level] += 1

    decided = sum(counts.values())
    return {
        "counts": counts,
        "decided": decided,
        "undecided": len(undecided),
        "undecided_indices": undecided,
        # 확정된 것이 없으면 비율은 없다. 0.0으로 두면 "합니다체가 하나도 없다"로
        # 잘못 읽힌다.
        "formal_ratio": (counts["합니다체"] / decided) if decided else None,
        "polite_indices": [ev.index for ev in events if level_of(ev.text) == "해요체"],
    }
