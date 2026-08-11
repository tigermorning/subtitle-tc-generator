"""작품에 나오는 용어를 뽑아 조사한다 — 작업자가 공부하던 시간을 줄인다.

**여기가 실제로 시간을 먹는 자리다.** 작업자 말로는 작품마다 역사·문학·전쟁·의학·
생태계를 새로 공부해야 하고, 그 공부가 부족하면 오역이 난다. 1차 번역에서는 덜
드러나지만 2차부터 결정적이다.

기계가 사람보다 확실히 빠른 일이 자료 수집이다. 그래서 이 모듈은 **번역을 대신하지
않고 조사를 대신한다.**

    ① 뽑는다     대본에서 고유명사·약어·전문 용어 후보를 긁는다
    ② 확인한다   국립국어원 외래어 표기 용례에서 **규범 표기**를 찾는다
    ③ 남긴다     못 찾은 것은 '확인 필요'로 두고 근거를 함께 적는다

**근거 없는 표기를 정답처럼 내지 않는다.** 규범 용례에서 온 것과 모델이 지어낸
것을 반드시 구분해서 낸다 — 작업자 자료에도 "NOTE/비고 란에는 내가 찾아 넣었을 때
출처 표기"라고 되어 있다. 출처가 없는 표기는 검수에서 되돌아온다.

결과는 KNP 시트에 그대로 붙일 수 있는 표로 낸다. 작업자가 어차피 만드는 표다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# 대문자로 시작하는 낱말이 이어지는 덩어리. `Royal Belum State Park`처럼 여러 낱말이
# 한 이름인 경우가 많아 낱말 단위로 자르면 못 쓴다.
PROPER = re.compile(r"\b([A-Z][a-z'’\-]+(?:\s+(?:of|de|van|von|der|la|le|el)\s+|\s+)?"
                    r"(?:[A-Z][a-z'’\-]+\s*){0,3})")
ACRONYM = re.compile(r"\b([A-Z]{2,6})\b")
SENTENCE_START = re.compile(r"(?:^|[.!?]\s+)([A-Z][a-z'’\-]+)")

# 문장 첫머리에 와서 대문자가 된 흔한 낱말들. 이름으로 잘못 잡으면 표가 쓰레기가 된다.
COMMON = {
    "the", "this", "that", "these", "those", "there", "then", "they", "them", "their",
    "and", "but", "for", "with", "what", "when", "where", "which", "who", "why", "how",
    "you", "your", "yes", "not", "now", "one", "two", "all", "any", "can", "did", "does",
    "have", "has", "had", "her", "his", "him", "she", "our", "out", "own", "was", "were",
    "will", "would", "should", "could", "just", "like", "look", "make", "many", "more",
    "most", "much", "need", "never", "next", "okay", "only", "over", "right", "said",
    "same", "some", "still", "sure", "take", "tell", "than", "thank", "think", "time",
    "well", "were", "well", "here", "hey", "let", "get", "got", "good", "great", "come",
    "going", "gonna", "want", "know", "really", "maybe", "because", "before", "after",
    "about", "again", "already", "always", "another", "anything", "everything", "someone",
    "something", "sorry", "please", "listen", "wait", "stop", "yeah", "oh", "no", "my",
    "i", "we", "he", "it", "a", "an", "in", "on", "at", "to", "of", "is", "are", "am",
    "do", "if", "so", "up", "us", "me", "by", "or", "as", "be", "been", "from", "were",
}


@dataclass
class Term:
    source: str                  # 원어 표기
    count: int = 1               # 몇 번 나오는지
    kind: str = "unknown"        # person | place | acronym | technical | unknown
    korean: str = ""             # 제안 표기
    origin: str = ""             # 근거 — 어디서 온 표기인지
    wrong: list[str] = field(default_factory=list)   # 흔한 오표기
    context: str = ""            # 처음 나온 자리
    meaning: str = ""            # 이게 무엇인지 한 줄 설명

    @property
    def confirmed(self) -> bool:
        """규범·용어집에서 온 표기인지. 모델이 지어낸 것은 아니다."""
        return bool(self.korean) and self.origin not in ("", "모델 제안")


def extract(texts: list[str], min_count: int = 1) -> list[Term]:
    """대본에서 조사할 만한 것을 긁는다.

    **적게 뽑기보다 놓치지 않는 쪽으로 기운다.** 표에서 지우는 것은 한 번이면 되고,
    빠진 것은 오역이 되어 돌아온다.
    """
    counts: Counter = Counter()
    kinds: dict[str, str] = {}
    contexts: dict[str, str] = {}

    # **같은 낱말이 소문자로도 나오면 이름이 아니다.** `Nice to meet you`의 `Nice`가
    # 도시 니스로 조사되어 나온 적이 있다(2026-08-11). 문장 첫머리라서 대문자가 된
    # 것뿐인지는 말뭉치 전체를 보면 알 수 있다 — 목록으로 거르는 것보다 정확하다.
    lowercase_seen = set()
    for text in texts:
        for word in re.findall(r"\b[a-z][a-z'’\-]+\b", text):
            lowercase_seen.add(word)

    for text in texts:
        line = re.sub(r"\s+", " ", text).strip()
        if not line:
            continue

        # 문장 첫머리라서 대문자가 된 흔한 낱말은 뺀다.
        starters = {m.group(1) for m in SENTENCE_START.finditer(line)}

        for match in PROPER.finditer(line):
            name = match.group(1).strip(" ,.-")
            if not name or len(name) < 2:
                continue
            words = name.split()
            if len(words) == 1:
                lowered = name.lower()
                if lowered in COMMON or lowered in lowercase_seen:
                    continue
                # 줄임말(`It's`, `That's`)은 이름이 아니다.
                if "'" in name or "’" in name:
                    continue
                # 경칭만 남은 것도 버린다.
                if lowered in ("mr", "mrs", "ms", "dr", "sir", "miss"):
                    continue
            counts[name] += 1
            kinds.setdefault(name, "place" if len(words) > 1 else "person")
            contexts.setdefault(name, line)

        for match in ACRONYM.finditer(line):
            name = match.group(1)
            if name in ("I", "A", "OK"):
                continue
            counts[name] += 1
            kinds.setdefault(name, "acronym")
            contexts.setdefault(name, line)

    # 긴 이름이 잡혔으면 그 안의 짧은 조각은 버린다(`Royal Belum` vs `Royal Belum State Park`).
    names = sorted(counts, key=len, reverse=True)
    dropped: set[str] = set()
    for i, long_name in enumerate(names):
        for short_name in names[i + 1:]:
            if short_name in dropped or short_name == long_name:
                continue
            if re.search(rf"\b{re.escape(short_name)}\b", long_name):
                dropped.add(short_name)

    return sorted(
        (Term(name, counts[name], kinds.get(name, "unknown"), context=contexts.get(name, ""))
         for name in counts if name not in dropped and counts[name] >= min_count),
        key=lambda t: (-t.count, t.source))


def research(terms: list[Term], lookup=None, glossary: dict | None = None,
             web: bool = False, progress=None) -> list[Term]:
    """규범 표기를 찾아 채운다.

    `lookup`은 `(원어) -> [{source, korean, category, wrong_marks}]` 꼴이면 된다.
    한국어 교정기의 `dictionary.terms.lookup_by_source`가 그 계약을 만족한다 —
    국립국어원 어문 규범 API를 부른다.

    **못 찾은 것을 지어내지 않는다.** 빈칸으로 두고 사람이 채우게 한다.
    """
    say = progress or (lambda _m: None)
    glossary = glossary or {}

    for term in terms:
        if term.source in glossary:
            term.korean, term.origin = glossary[term.source], "KNP/용어집"
            continue
        if lookup is None:
            continue
        try:
            rows = lookup(term.source) or []
        except Exception as exc:            # 네트워크·키 문제로 조사가 멈추면 안 된다
            say(f"조사 실패({term.source}): {exc}")
            continue
        best = _best_row(rows, term.source)
        if best:
            term.korean = best.get("korean") or best.get("segment") or ""
            term.origin = "국립국어원 외래어 표기 용례"
            term.wrong = [w for w in (best.get("wrong_marks") or []) if w]
            if best.get("category"):
                term.kind = best["category"]

    # **규범 용례는 좁다.** 실제 작업에서 걸리는 지명·부대명·생물명이 거기 없다
    # (사용자 지적 2026-08-11: "국립국어원 외래어 용례만으로는 부족한 것들이 많다").
    # 남은 것만 밖에서 찾는다 — **낱말만 나간다**(`webterms` 첫머리 참고).
    if web:
        from .webterms import korean_title

        left = [t for t in terms if not t.korean]
        say(f"규범 용례에 없는 {len(left)}개를 밖에서 찾습니다(낱말만 보냅니다)")
        for term in left:
            try:
                hit = korean_title(term.source)
            except Exception as exc:
                say(f"조사 실패({term.source}): {exc}")
                continue
            if hit and not hit.ambiguous:
                term.korean, term.origin = hit.korean, hit.note
            elif hit:
                # 후보만 알려 주고 칸은 비워 둔다. 채워 놓으면 그대로 나간다.
                term.origin = f"후보: {hit.korean} / {hit.note}"
    return terms


EXPLAIN_SYSTEM = (
    "당신은 영상 번역가를 돕는 조사원입니다. 대본에 나온 용어가 무엇인지 한 줄로 "
    "설명합니다.\n"
    "- 한 줄, 40자 이내. 번역가가 오역을 피할 만큼만 짧게.\n"
    "- 분야를 앞에 답니다: [군사] [의학] [생태] [법률] [역사] [지명] [인명] [기타]\n"
    "- **모르면 '모름'이라고 씁니다.** 지어내지 마세요. 지어낸 설명이 오역을 만듭니다.\n"
    "- 번호를 그대로 붙여 같은 개수로 냅니다."
)


def explain(terms: list[Term], translator, batch: int = 10, progress=None) -> list[Term]:
    """용어가 무엇인지 한 줄로 채운다 — **로컬 모델로**.

    표기(어떻게 적는가)와 설명(무엇인가)은 다른 문제다. 오역은 표기를 몰라서가
    아니라 **무엇인지 몰라서** 난다("작업자 자료: 작품마다 역사·의학·생태를 공부").

    설명은 밖으로 나가지 않는다 — 로컬 모델이라 대본 문맥을 함께 줘도 된다. 표기와
    달리 문맥이 있어야 쓸모가 있다.

    **모르면 모른다고 적게 한다.** 지어낸 설명은 없는 것보다 나쁘다. 그리고 설명은
    표기가 아니므로 `confirmed`를 바꾸지 않는다 — 사람이 판단할 재료일 뿐이다.
    """
    say = progress or (lambda _m: None)
    from .translate import _parse_numbered

    todo = [t for t in terms if not t.meaning]
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        say(f"용어 설명 {start + 1}~{start + len(chunk)} / {len(todo)}")
        lines = []
        for i, term in enumerate(chunk, 1):
            context = term.context[:90].replace("\n", " ")
            lines.append(f"{i}. {term.source} — 나온 자리: {context}")
        reply = translator.ask(EXPLAIN_SYSTEM,
                               "다음 용어가 무엇인지 한 줄로 설명하세요.\n\n"
                               + "\n".join(lines))
        got = _parse_numbered(reply, list(range(1, len(chunk) + 1)))
        for i, term in enumerate(chunk, 1):
            text = (got.get(i) or "").strip()
            # 모델이 굵게 표시(`**[법률]**`)를 붙인다. 표에 들어가면 눈에 거슬린다.
            text = re.sub(r"\*+", "", text).strip()
            if text and "모름" not in text[:6]:
                term.meaning = text.splitlines()[0][:60]
    return terms


def _best_row(rows: list[dict], source: str) -> dict | None:
    """원어가 정확히 같은 줄을 고른다. 비슷한 것을 집으면 엉뚱한 표기가 들어간다."""
    lowered = source.lower()
    exact = [r for r in rows if (r.get("source") or "").strip().lower() == lowered]
    return (exact or rows or [None])[0]


def to_tsv(terms: list[Term]) -> str:
    """KNP 시트에 그대로 붙일 수 있는 표.

    칸 순서는 작업자 KNP와 맞춘다(Source / Target / Type / Note). 근거를 Note에
    적는 것도 그 관례를 따른 것이다.
    """
    lines = ["Source Language\tTarget Language\tType\tNote\t설명\t횟수\t처음 나온 자리"]
    for term in terms:
        note = term.origin
        if term.wrong:
            note = f"{note} / 오표기: {', '.join(term.wrong[:3])}" if note else \
                   f"오표기: {', '.join(term.wrong[:3])}"
        if not term.korean:
            note = (note + " / " if note else "") + "확인 필요"
        lines.append("\t".join([
            term.source, term.korean, term.kind, note,
            term.meaning.replace("\t", " "), str(term.count),
            term.context.replace("\t", " ")[:60],
        ]))
    return "\n".join(lines)


def summarize(terms: list[Term]) -> dict:
    return {
        "total": len(terms),
        "confirmed": sum(1 for t in terms if t.confirmed),
        "unknown": sum(1 for t in terms if not t.korean),
    }
