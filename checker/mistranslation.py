"""원문과 번역을 견주어 **뜻이 새어 나간 자리**를 찾는다.

오역은 자막 작업에서 가장 비싼 실수다. 문체는 감수에서 고쳐지지만 오역은 그대로
납품된다. 그래서 1차 직후에 잡아야 한다.

## 확정과 추정을 갈라 둔다

백로그에 이 검사들을 "확정"이라고 적었는데 **넷 중 둘은 확정이 아니다.** 짓다가
드러났으므로 여기 바로잡아 둔다.

    확정   화자 표시 — `[민수]`가 사라지거나 바뀌면 구조가 깨진 것이다
    확정   용어      — 통일표에 있는 표기를 쓰지 않은 것 (표가 정답이다)
    추정   부정      — `I don't know` -> `몰라요`. 부정 표시가 없어도 부정이다
    추정   숫자      — `in 5 minutes` -> `곧`. 자막은 숫자를 버리기도 한다

그래서 **전부 플래그로만 낸다.** 규정 위반 목록에 섞지 않는다(규칙 4: 추정으로
자동 교정을 하면 틀렸을 때 사람이 원인을 못 찾는다).

## 어느 단계에서 재는가

**1차 직후다.** 1차는 압축하지 않기로 했으므로(문체·간결은 3차의 일) 이때 숫자나
부정이 빠졌으면 오역일 가능성이 높다. 3차를 지난 자막에 같은 검사를 걸면 정상적인
압축을 오역으로 부른다 — `in 5 minutes` -> `곧 가요`는 3차에서 옳은 선택이다.

## 왜 역번역을 여기서 쓰지 않나

역번역은 시간이 두 배다. 이 층은 **공짜로 잡히는 것**만 잡고, 남은 의심분만 역번역에
넘긴다(`docs/BACKLOG.md` T7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Event
from .text import strip_tags

# 화자 표시·효과음. 번역이 이것을 잃으면 구조가 깨진다.
_TAG = re.compile(r"[\[(]([^)\]]+)[\])]")

# 원문의 숫자. 연도·시각·수량이 다 걸린다.
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")

# 한국어가 숫자를 글자로 적는 방식. 이것들이 있으면 숫자를 옮긴 것으로 본다.
#
# **한 음절 한자 수사를 그냥 넣으면 안 된다.** 처음에 `일 이 사 오 구 십 만`을 목록에
# 넣었더니 `잠깐만요`가 '숫자 있음'으로 판정됐다 — `만`이 걸린 것이다. 그런 낱말은
# 아무 한국어에나 있어서 검사가 사실상 돌지 않았다.
#
# 그래서 한자 수사는 **두 음절 이상이거나 단위가 뒤에 붙을 때만** 수사로 본다.
# 고유어 수사는 두 음절이라 그대로 써도 된다.
#
# 판정을 **넉넉한 쪽으로 기울인다.** 여기서 '숫자 있음'을 놓치면 헛플래그가 되고,
# 반대로 넉넉하면 못 잡을 뿐이다 — 오답이 플래그보다 비싸다.
_SINO = "영일이삼사오육칠팔구십백천만억조"
_COUNTERS = ("개", "명", "분", "초", "시간", "시", "년", "월", "일", "번", "층", "살",
             "원", "달러", "미터", "킬로", "퍼센트", "배", "마리", "권", "장", "병",
             "잔", "대", "척", "주", "달", "해", "쪽", "가지", "군데", "차례")
_KO_NUMBER = re.compile(
    r"\d"
    r"|하나|둘|셋|넷|다섯|여섯|일곱|여덟|아홉|열|스물|서른|마흔|쉰|예순|일흔|여든|아흔"
    r"|반|몇|여러|수십|수백|수천"
    rf"|[{_SINO}]{{2,}}"
    rf"|[{_SINO}]\s*(?:{'|'.join(_COUNTERS)})"
)

# 원문의 부정. `n't`는 따로 본다(`don't`, `can't`).
_EN_NEGATION = re.compile(
    r"\b(?:not|never|no|none|nothing|nobody|nowhere|neither|nor|without|"
    r"cannot|can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't|"
    r"haven't|hasn't|hadn't|shouldn't|wouldn't|couldn't|ain't)\b|n't\b",
    re.IGNORECASE)

# 한국어의 부정. **표시가 있는 것과 낱말 자체가 부정인 것을 함께 본다** —
# `I don't know` -> `몰라요`에는 부정 표시가 없다.
_KO_NEGATION = (
    "안 ", "안돼", "안 돼", "못 ", "못하", "없", "아니", "말고", "말아", "마세요", "마라",
    "지 않", "지도 않", "지 못", "지 말",
    # 낱말 자체가 부정
    "모르", "몰라", "싫", "그만", "금지", "불가", "거절", "거부", "빼", "덜",
    "아무도", "아무것도", "절대", "전혀", "결코",
)


@dataclass
class Flag:
    """확인이 필요한 자리. **위반이 아니다** — 사람이 보고 판단한다."""

    event_index: int
    kind: str                    # speaker | glossary | negation | number
    reason: str
    source: str = ""
    target: str = ""
    certain: bool = False        # 구조·표가 근거인가(확정), 아니면 추정인가

    def to_dict(self) -> dict:
        return {"event_index": self.event_index, "kind": self.kind,
                "reason": self.reason, "source": self.source, "target": self.target,
                "certain": self.certain}


def _has_any(text: str, needles) -> bool:
    return any(n in text for n in needles)


def _body(text: str) -> str:
    """표시를 뗀 대사만. 화자명·효과음 안의 글자를 대사로 세지 않는다."""
    return _TAG.sub(" ", strip_tags(text))


def check_speaker(source: str, target: str) -> str:
    """화자 표시·효과음이 살아 있는가. **확정이다** — 개수가 다르면 구조가 깨졌다.

    안의 글자는 견주지 않는다. 화자명은 한국어로 옮기는 대상이므로 달라지는 것이
    정상이다(`[Sarah]` -> `[사라]`).
    """
    before, after = _TAG.findall(source), _TAG.findall(target)
    if len(before) == len(after):
        return ""
    if len(after) < len(before):
        return f"화자 표시·효과음이 {len(before)}개에서 {len(after)}개로 줄었습니다"
    return f"화자 표시·효과음이 {len(before)}개에서 {len(after)}개로 늘었습니다"


def check_negation(source: str, target: str) -> str:
    """부정이 사라졌는가. **추정이다.**

    부정 소실은 뜻을 정반대로 뒤집으므로 가장 치명적이다. 그런데 한국어는 부정 표시
    없이 부정할 수 있어(`몰라요`, `없어요`) 낱말 목록으로 거를 수밖에 없고, 목록은
    반드시 새는 곳이 있다 — 그래서 지적이 아니라 플래그다.
    """
    if not _EN_NEGATION.search(source):
        return ""
    if _has_any(_body(target), _KO_NEGATION):
        return ""
    return "원문에 부정이 있는데 번역에서 보이지 않습니다"


def check_number(source: str, target: str) -> str:
    """숫자가 사라졌는가. **추정이다.**

    자막은 숫자를 버리기도 한다(`in 5 minutes` -> `곧`). 그래서 1차에서만 뜻이 있다 —
    1차는 압축하지 않기로 했으므로 이때 빠진 숫자는 옮기지 않은 것일 가능성이 높다.

    한국어가 숫자를 글자로 적었으면(`다섯`, `열`) 옮긴 것으로 본다. 단위 변환도
    걸리지 않게 **어떤 숫자든 하나라도 있으면** 넘긴다 — 작업자 자료 146행이
    "화자의 국적을 잘 따져서 단위를 다뤄야 함"이라고 하므로 값이 달라지는 것이 정상이다.
    """
    found = _DIGITS.findall(source)
    if not found:
        return ""
    if _KO_NUMBER.search(_body(target)):
        return ""
    return f"원문의 숫자({', '.join(found[:3])})가 번역에서 보이지 않습니다"


def check_glossary(source: str, target: str, glossary) -> str:
    """통일표에 있는 표기를 썼는가. **확정이다** — 표가 정답을 정해 준다.

    다만 고치지는 않는다. 문맥상 그 표기를 안 쓰는 것이 맞을 때가 있다(규칙 3).
    """
    pairs = getattr(glossary, "terms", None) or {}
    missed = []
    for term, korean in pairs.items():
        if not korean or not term:
            continue
        if re.search(rf"\b{re.escape(term)}\b", source, re.IGNORECASE) \
                and korean not in target:
            missed.append(f"{term} -> {korean}")
    if not missed:
        return ""
    return "통일표 표기를 쓰지 않았습니다: " + ", ".join(missed[:3])


def scan(events: list[Event], source: dict[int, str], glossary=None) -> list[Flag]:
    """1차 번역을 원문과 견준다. 확정을 앞에, 추정을 뒤에 둔다.

    `source`는 자막 번호별 원문이다. 없는 번호는 넘긴다 — 원문 없이 견줄 수 없다.
    """
    flags: list[Flag] = []
    for ev in events:
        before = source.get(ev.index)
        if not before:
            continue
        after = ev.text

        for kind, reason, certain in (
            ("speaker", check_speaker(before, after), True),
            ("glossary", check_glossary(before, after, glossary) if glossary else "", True),
            ("negation", check_negation(before, after), False),
            ("number", check_number(before, after), False),
        ):
            if reason:
                flags.append(Flag(ev.index, kind, reason, before, after, certain))

    # 확정을 먼저 보여 준다. 사람이 위에서부터 처리하면 값이 큰 것부터 처리된다.
    flags.sort(key=lambda f: (not f.certain, f.event_index))
    return flags


def summarize(flags: list[Flag]) -> dict:
    counts: dict[str, int] = {}
    for flag in flags:
        counts[flag.kind] = counts.get(flag.kind, 0) + 1
    return {"total": len(flags), "by_kind": counts,
            "certain": sum(1 for f in flags if f.certain),
            "estimated": sum(1 for f in flags if not f.certain)}
