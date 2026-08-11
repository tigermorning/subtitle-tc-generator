"""효과음 어휘 사전 — 지적에 **대안**을 붙인다.

지적만 하는 도구는 "그럼 뭐라고 쓰죠"라는 질문을 남긴다. 넷플릭스가 `[~소리]`·
`[~가 들린다]`를 지양한다고 알려 주는 것만으로는 부족하고, 같은 뜻의 표기를
보여 줘야 고칠 수 있다.

사전은 작업자가 실제 납품하며 모은 목록이다(464개). **검사가 아니라 제안이다** —
목록에 없다고 틀린 표기가 아니고, 어떤 소리인지는 영상을 봐야 안다. 그래서 자동
교정 대상이 아니며 후보를 여러 개 보여 주고 사람이 고르게 한다.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

LEXICON_PATH = Path(__file__).resolve().parent.parent / "rules" / "lexicon" / "ko-sdh-effects.yaml"

# 후보를 찾을 때 무시할 흔한 말. 이것으로 이어 붙이면 아무 항목이나 걸린다.
_STOPWORDS = {"소리", "효과음", "하는", "나는", "들린다", "들리는", "같은", "이는", "그는", "낸다"}
_TOKEN = re.compile(r"[가-힣]{2,}")
# 조사를 떼고 견준다. `소리가`가 `소리`로 줄어야 불용어에 걸리고,
# `문을`과 `문이`가 같은 말로 묶인다.
_JOSA = ("으로", "에서", "에게", "이랑", "하고", "가", "이", "을", "를", "은", "는", "의", "에", "로", "와", "과")


def _stem(word: str) -> str:
    for josa in _JOSA:
        if len(word) > len(josa) + 1 and word.endswith(josa):
            return word[: -len(josa)]
    return word


def _tokens(text: str) -> list[str]:
    out = []
    for raw in _TOKEN.findall(text):
        word = _stem(raw)
        if word and word not in _STOPWORDS and len(word) >= 2:
            out.append(word)
    return out


@lru_cache(maxsize=1)
def _load() -> list[tuple[str, str]]:
    """[(분류, 표기)] 목록. 사전이 없으면 조용히 빈 목록을 준다 — 제안은 부가 기능이다."""
    if not LEXICON_PATH.is_file():
        return []
    data = yaml.safe_load(LEXICON_PATH.read_text(encoding="utf-8")) or {}
    entries = []
    for category, terms in (data.get("categories") or {}).items():
        for term in terms or []:
            entries.append((category, term))
    return entries


def suggest(marker: str, limit: int = 3) -> list[str]:
    """`[문 닫는 소리]` 같은 표기에 대해 같은 뜻의 후보를 돌려준다.

    맞추는 방법은 단순하다 — 표기 안의 명사를 뽑아 사전 항목에 그 말이 들어 있으면
    후보로 본다. 형태소 분석을 쓰지 않는 이유는 제안이 틀려도 손해가 없고(사람이
    고른다) 적재 비용이 크기 때문이다.
    """
    words = _tokens(marker)
    if not words:
        return []

    scored: list[tuple[int, str]] = []
    for _category, term in _load():
        if term == marker:
            continue
        # 낱말 단위로 견준다. 통짜 부분 문자열로 맞추면 `닫는`이 `깨닫는`에 걸린다
        # (실측에서 `[문 닫는 소리]`가 `[깨닫는 탄성]`을 후보로 냈다).
        term_words = _tokens(term)
        score = sum(1 for w in words if any(w == t or t.startswith(w) or w.startswith(t)
                                            for t in term_words))
        if score and any(t.startswith(words[0]) or words[0].startswith(t) for t in term_words):
            score += 1  # 앞말이 겹치면 더 가깝다고 본다
        if score:
            scored.append((score, term))

    if not scored:
        # 낱말이 안 맞아도 분류 이름이 맞으면 그 갈래를 보여 준다
        # (`[발걸음 소리가 들린다]`는 `발소리` 분류에 답이 있는데 낱말은 다르다).
        head = words[0][:1]
        for category, term in _load():
            leaf = category.split(" > ")[-1]
            if leaf.startswith(head) and term != marker:
                scored.append((1, term))

    scored.sort(key=lambda x: (-x[0], len(x[1])))
    out: list[str] = []
    for _score, term in scored:
        if term not in out:
            out.append(term)
        if len(out) >= limit:
            break
    return out


def suggest_text(marker: str, limit: int = 3) -> str:
    """리포트에 붙일 한 줄. 후보가 없으면 빈 문자열."""
    found = suggest(marker, limit)
    return f"이렇게 쓸 수 있습니다: {' / '.join(found)}" if found else ""
