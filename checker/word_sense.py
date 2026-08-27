"""영어 원어 표현의 숨은 뜻 사전 — 1차 번역 프롬프트에 참고용 힌트로 붙인다.

교정기(`korean.py`)가 보는 건 완성된 한국어 문장의 표기 규범(맞춤법·띄어쓰기·
외래어 표기)이다. 국립국어원 API들(어문 규범·표준국어대사전·우리말샘)도 전부
**한국어 단일언어** 자원이라 한국어 단어의 정의·방언형만 안다.

이 사전이 보는 건 다르다 — 원어(영어) 표현이 액면 뜻과 다를 때다(little=하찮은,
block≠블록 같은 것). 원어를 아예 안 보는 교정기로는 잡을 수 없는 자리라 따로
둔다(2026-08-27, 사용자 확인).

**검사가 아니라 참고다.** 매칭은 낱말 경계 문자열 포함 여부로만 하므로 문맥과
무관하게 걸릴 수 있다 — 모델에게 참고하라고 보여 줄 뿐 강제하지 않는다. 그래서
자막 배치 전체가 아니라 **그 배치의 원문에 실제로 나온 표현만** 골라 붙인다 —
27개를 매번 다 보여 주면 프롬프트만 커지고 안 걸리는 표현은 소음이 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

LEXICON_PATH = Path(__file__).resolve().parent.parent / "rules" / "lexicon" / "en-ko-word-sense.yaml"

_PAREN = re.compile(r"\([^()]*\)")


@dataclass
class SenseEntry:
    phrase: str
    note: str
    patterns: tuple[re.Pattern, ...]


def _variants(phrase: str) -> list[str]:
    """표시용 `phrase`에서 매칭용 낱말을 뽑는다.

    괄호 안 설명(`(문두)`·`(that)`)과 `~`(자리표) 표시는 실제 대사에 그대로
    나오지 않으므로 뗀다. `/`로 나열된 것은 각각 매칭 후보가 된다."""
    cleaned = _PAREN.sub("", phrase).replace("~", "")
    parts = [p.strip(" .,:;") for p in cleaned.split(" / ")]
    return [p for p in parts if p]


@lru_cache(maxsize=1)
def _load() -> tuple[SenseEntry, ...]:
    """사전이 없으면 조용히 빈 목록을 준다 — 힌트는 부가 기능이다."""
    if not LEXICON_PATH.is_file():
        return ()
    data = yaml.safe_load(LEXICON_PATH.read_text(encoding="utf-8")) or {}
    entries: list[SenseEntry] = []
    for raw in data.get("entries") or []:
        phrase = (raw.get("phrase") or "").strip()
        note = (raw.get("note") or "").strip()
        if not phrase or not note:
            continue
        # 자동으로 뽑은 낱말이 실제 문장과 안 맞는 자리(예: 자리표가 낀 예문형
        # 항목)는 사전에 `match`로 직접 지정한다.
        override = raw.get("match")
        variants = [override] if override else _variants(phrase)
        patterns = tuple(re.compile(rf"\b{re.escape(v)}\b", re.IGNORECASE)
                         for v in variants if v)
        if patterns:
            entries.append(SenseEntry(phrase, note, patterns))
    return tuple(entries)


def matches(text: str, limit: int = 5) -> list[SenseEntry]:
    """원문 한 덩어리에서 걸리는 표현을 사전에 실린 순서로 찾는다."""
    found = []
    for entry in _load():
        if any(p.search(text) for p in entry.patterns):
            found.append(entry)
        if len(found) >= limit:
            break
    return found


def hint(text: str, limit: int = 5) -> str:
    """번역 프롬프트에 붙일 한 줄. 걸리는 것이 없으면 빈 문자열."""
    found = matches(text, limit)
    if not found:
        return ""
    body = "; ".join(f"{e.phrase} → {e.note}" for e in found)
    return f"\n액면 뜻과 다를 수 있는 표현(참고만 하세요): {body}"
