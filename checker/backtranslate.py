"""번역을 원어로 되돌려 원문과 견준다 — **뜻이 새어 나간 자리를 사람이 보게 한다.**

## 왜 역번역인가

읽기 편해서가 아니다. **비교가 같은 언어끼리 되기 때문이다.**

영어와 한국어를 직접 견주려면 다국어 임베딩이 필요하고(torch ~2GB, exe가 불어난다),
점수만 나와서 무엇이 틀렸는지는 못 본다. 역번역을 거치면 **의존성 없이 낱말로 재고**,
사람에게 보일 근거가 그 자체로 남는다.

    #42  원문    I never said I'd go alone
         한국어  혼자 가겠다고 했어요
         역번역  I said I would go alone        <- never가 사라졌다

## 설계를 바로잡았다

`docs/BACKLOG.md`에 "층1을 통과했지만 **낱말 겹침이 낮은 자막만** 역번역한다"고 적어
두었는데 **그건 순환이다** — 겹침은 역번역을 해야 계산된다. 역번역 전에는 어느 자막이
의심스러운지 알 방법이 없다.

그래서 **전수로 돌리고, 점수로 골라 사람에게 보인다.** 한 회차 더 도는 비용이고
(감수 회차와 같은 크기), 고르는 일은 점수가 나온 뒤에 한다.

## 임계값을 두지 않는다

몇 점 이하가 오역인지는 실제 작업물로 재야 안다. 근거 없는 임계값은 오답 공장이다
(다큐 합니다체 비율에서 같은 판단을 했다). 그래서 **점수 낮은 순으로 정렬해 상위
몇 개를 보인다** — 판정이 아니라 순위다.

## 어디에 쓰나

    1차 직후   층1이 놓친 뜻 변화 (숫자·부정으로 안 잡히는 것)
    3차 끝     **윤문이 뜻을 깎았는지.** 2차·3차가 글자를 줄이면서 의미를 버릴 수
               있어서, 1차만 검증하면 그 유실을 못 잡는다
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Event
from .translate import _parse_numbered
from .text import strip_tags

# **말 그대로 되돌리게 한다.** 모델이 다듬으면 좋은 번역도 점수가 떨어져 헛플래그가 된다.
SYSTEM = (
    "You are a literal back-translator. Translate each Korean subtitle back into "
    "{lang} **word for word**.\n"
    "- Do NOT improve, polish, or shorten. Awkward {lang} is correct here.\n"
    "- Keep what is there and add nothing. If a word is missing in the Korean, "
    "leave it missing.\n"
    "- Keep speaker names and sound effects in brackets as they are.\n"
    "- Reply with the same numbers and the same number of lines. No explanations."
)

LANGUAGES = {"en": "English", "ja": "Japanese", "zh": "Chinese", "es": "Spanish",
             "fr": "French", "de": "German"}

# 내용어만 견준다. 기능어는 어느 문장에나 있어 겹침을 부풀린다.
STOPWORDS = {
    "a", "an", "the", "is", "are", "am", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "will", "would", "shall", "should",
    "can", "could", "may", "might", "must", "of", "to", "in", "on", "at", "by",
    "for", "with", "from", "as", "that", "this", "these", "those", "it", "its",
    "and", "or", "but", "so", "if", "then", "than", "there", "here", "you", "your",
    "i", "me", "my", "we", "us", "our", "he", "him", "his", "she", "her", "they",
    "them", "their", "what", "who", "which", "when", "where", "how", "why",
    "about", "just", "very", "too", "also", "up", "out", "down", "over",
}

# 빠지면 뜻이 뒤집히는 낱말. **기능어라도 빼지 않는다.**
KEEP = {"not", "no", "never", "none", "nothing", "nobody", "nowhere", "without",
        "neither", "nor", "cannot", "don't", "didn't", "doesn't", "won't", "can't"}

_WORD = re.compile(r"[A-Za-z0-9']+")
_TAG = re.compile(r"[\[(][^)\]]*[\])]")

# **줄임말을 펴서 양쪽을 같게 만든다.** 안 펴면 원문 `don't`와 역번역 `do not`이
# 어긋난 것으로 보인다 — 가장 중요한 신호인 부정이 바로 그 무늬라 그냥 두면 못 쓴다.
# `I'd`/`I would`도 좋은 번역의 점수를 깎았다(실측 0.80).
#
# 같은 규칙을 양쪽에 걸므로 `I'd`가 would인지 had인지 모르는 문제는 견주기에서
# 서로 상쇄된다. 줄기 뽑기(`go`/`went`)와 다르다 — 그쪽은 규칙이 아니라 짐작이다.
#
# **순서가 중요하다.** 사전은 넣은 순서를 지키므로 구체적인 것을 앞에 둔다. 일반
# 규칙 `n't`를 먼저 걸면 `can't`가 `ca not`이 되어 역번역의 `can not`과 어긋난다
# (실측 0.67).
CONTRACTIONS = {
    "cannot": "can not", "can't": "can not", "won't": "will not",
    "shan't": "shall not", "ain't": "is not",
    "n't": " not", "'re": " are", "'ve": " have", "'ll": " will", "'m": " am",
    "'d": " would", "let's": "let us", "gonna": "going to",
    "wanna": "want to", "gotta": "got to",
}


def _expand(text: str) -> str:
    for short, long in CONTRACTIONS.items():
        text = text.replace(short, long)
    return text


def content_words(text: str) -> list[str]:
    """견줄 낱말만 남긴다. 표시 안의 글자는 대사가 아니라 뺀다.

    어미 변화는 다루지 않는다(`go`/`went`를 다르게 센다). **줄기 뽑기를 넣으면
    맞을 때도 있고 틀릴 때도 있는데, 틀리면 좋은 번역의 점수를 깎아 헛플래그가 된다.**
    지금은 넣지 않고, 점수를 판정이 아니라 순위로 쓰는 것으로 대신한다.
    """
    body = _expand(_TAG.sub(" ", strip_tags(text)).lower())
    return [w for w in _WORD.findall(body) if w in KEEP or w not in STOPWORDS]


def overlap(source: str, back: str) -> float | None:
    """원문의 내용어가 역번역에 얼마나 남았는가. 0.0~1.0, 셀 것이 없으면 `None`.

    **원문 기준으로 센다**(재현율). 역번역이 말을 덧붙이는 것은 이 검사의 관심이
    아니고, 원문에 있던 것이 사라진 것이 오역이다.
    """
    want = content_words(source)
    if not want:
        return None
    got = set(content_words(back))
    return sum(1 for w in want if w in got) / len(want)


@dataclass
class Divergence:
    event_index: int
    score: float
    source: str
    korean: str
    back: str
    missing: list[str]           # 원문에 있었는데 역번역에 없는 내용어

    def to_dict(self) -> dict:
        return {"event_index": self.event_index, "score": round(self.score, 3),
                "source": self.source, "korean": self.korean, "back": self.back,
                "missing": self.missing}


def run(events: list[Event], translator, language: str = "en", batch: int = 12,
        progress=None) -> dict[int, str]:
    """한국어 자막을 원어로 되돌린다. 자막 번호별 역번역을 돌려준다.

    **자막을 바꾸지 않는다.** 이 단계는 읽기만 한다.
    """
    say = progress or (lambda _m: None)
    label = LANGUAGES.get(language, language)
    system = SYSTEM.replace("{lang}", label)
    out: dict[int, str] = {}

    for start in range(0, len(events), batch):
        chunk = events[start:start + batch]
        say(f"역번역 {start + 1}~{start + len(chunk)} / {len(events)}")
        prompt = ("Back-translate these Korean subtitles into "
                  f"{label}.\n\n"
                  + "\n".join(f"{e.index}. {e.text}" for e in chunk))
        try:
            reply = translator.ask(system, prompt)
        except Exception as exc:            # 한 묶음이 실패해도 나머지는 돈다
            say(f"역번역 실패({start + 1}~): {exc}")
            continue
        out.update(_parse_numbered(reply, [e.index for e in chunk]))
    return out


def compare(events: list[Event], source: dict[int, str],
            back: dict[int, str]) -> list[Divergence]:
    """원문과 역번역을 견준다. **점수 낮은 순**으로 정렬해 돌려준다.

    원문이나 역번역이 없는 번호는 넘긴다 — 견줄 것이 없으면 점수도 없다.
    """
    korean = {e.index: e.text for e in events}
    out: list[Divergence] = []
    for index, before in source.items():
        after = back.get(index)
        if not before or not after:
            continue
        score = overlap(before, after)
        if score is None:
            continue
        got = set(content_words(after))
        missing = [w for w in content_words(before) if w not in got]
        out.append(Divergence(index, score, before, korean.get(index, ""), after,
                              missing))
    out.sort(key=lambda d: (d.score, d.event_index))
    return out


def worst(divergences: list[Divergence], count: int = 20) -> list[Divergence]:
    """점수가 낮은 것부터 `count`개. **판정이 아니라 순위다.**

    몇 점 이하가 오역인지는 실제 작업물로 재야 알고, 재기 전에 임계값을 박으면
    오답 공장이 된다. 그래서 자르는 것은 점수가 아니라 개수다.
    """
    return divergences[:count] if count else list(divergences)


def summarize(divergences: list[Divergence]) -> dict:
    if not divergences:
        return {"total": 0}
    scores = sorted(d.score for d in divergences)
    mid = scores[len(scores) // 2]
    return {"total": len(scores),
            "mean": round(sum(scores) / len(scores), 3),
            "median": round(mid, 3),
            "min": round(scores[0], 3),
            # 원문 내용어가 절반도 안 남은 자막 수. **판정이 아니라 눈금이다** —
            # 어느 선이 오역인지는 실제 작업물로 재야 안다.
            "below_half": sum(1 for s in scores if s < 0.5)}


# --- 번호 밀림 ---------------------------------------------------------------
#
# 1차 번역은 자막을 12개씩 묶어 번호를 붙여 보낸다. **문장 하나가 자막 두 개에
# 걸치면**(`463. Everyone, this is Dr. Ryland Grace` / `464. from the United
# States.`) 모델이 앞 번호에 문장을 통째로 옮기고, 뒤 번호들에는 한 칸씩 당겨진
# 다음 대사를 넣는다. 번호는 다 있고 내용도 차 있어서 `_parse_numbered`의 번호
# 검사와 빈 번호 재질문을 전부 통과한다. 타임코드는 번호에 걸려 있으므로
# **대사가 말보다 먼저 뜨는 자막**이 조용히 나간다(exaone3.5 실측, 프로젝트
# 헤일 메리 영어 SDH 세 구간 431큐 중 약 21큐 — 0건인 구간부터 13큐 연쇄까지,
# 2026-09-24).
#
# 역번역이 이미 있으니 그것으로 잡는다: 역번역 N이 **제 원문보다 이웃 원문과 더
# 겹치면** 밀린 것으로 본다. 판정이 아니라 사람이 볼 자리 목록이다.
#
# 값은 위 실측 431큐에서 정했다. 이웃 비교만으로는 뽑은 29곳 중 21곳이 실제
# 밀림이었고, 틀린 8곳은 대부분 **이웃 원문이 내용어 한 낱말**("Personal.",
# "Name is")이라 그 낱말이 번역에 다시 나온 것이었다. 그래서 이웃 원문이 내용어
# 한 낱말이면, 제 원문과 하나도 안 겹칠 때만 잡는다 — 같은 431큐에서 23곳 중
# 21곳(값을 정한 자료로 잰 것이라 실제보다 좋게 나온 숫자다). 이 규칙은 연쇄 밀림의
# 가운데처럼 **어느 원문과도 안 겹치는 자리는 못 잡는다**. **자료 하나로 정한 값이다** —
# `tools/translate_shift_probe.py`로 다른 작품을 재면 다시 본다.
_SHIFT_REACH = 2        # 몇 칸까지 밀린 것을 보나 (실측 최대 2칸)
_SHIFT_NEAR = 0.5       # 이웃 원문 내용어가 이만큼은 역번역에 있어야 한다
_SHIFT_MARGIN = 0.25    # 그리고 제 원문보다 이만큼 더 겹쳐야 한다


@dataclass
class Shift:
    event_index: int
    from_index: int              # 이 자막에 실제로 들어온 것으로 보이는 원문 번호
    own: float                   # 제 원문과의 겹침
    neighbor: float              # from_index 원문과의 겹침
    source: str
    korean: str
    back: str

    def to_dict(self) -> dict:
        return {"event_index": self.event_index, "from_index": self.from_index,
                "own": round(self.own, 3), "neighbor": round(self.neighbor, 3),
                "source": self.source, "korean": self.korean, "back": self.back}


def shift_suspects(events: list[Event], source: dict[int, str],
                   back: dict[int, str]) -> list[Shift]:
    """번역이 이웃 자막의 대사를 담은 것으로 보이는 자리. 자막 순서대로 돌려준다."""
    korean = {e.index: e.text for e in events}
    order = [e.index for e in events if source.get(e.index)]
    out: list[Shift] = []
    for i, index in enumerate(order):
        after = back.get(index)
        if not after:
            continue
        own = overlap(source[index], after)
        if own is None:
            continue
        best, best_index = 0.0, None
        # 가까운 이웃부터 본다 — 점수가 같으면 가까운 쪽이 출처다.
        steps = [s for d in range(1, _SHIFT_REACH + 1) for s in (-d, d)]
        for step in steps:
            j = i + step
            if not 0 <= j < len(order):
                continue
            other = source[order[j]]
            score = overlap(other, after)
            if score is None or score <= best:
                continue
            if len(content_words(other)) < 2 and own > 0:
                continue
            best, best_index = score, order[j]
        if best_index is not None and best >= _SHIFT_NEAR and best >= own + _SHIFT_MARGIN:
            out.append(Shift(index, best_index, own, best, source[index],
                             korean.get(index, ""), after))
    return out
