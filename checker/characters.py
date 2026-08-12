"""등장인물을 뽑아 캐릭터 분석 문서를 만든다 — 조사를 대신한다.

**KNP 시트와 다른 문서다.** KNP는 고유명사 표기를 통일하고(`terms.py`), 이 문서는
말투와 인물 관계를 통일한다. 둘을 합치지 않는다 — 칸이 다르고 쓰는 자리가 다르다.

## 왜 필요한가

하나의 작품을 여러 작업자가 나누어 한다. 그래서 **말투가 사람마다 달라진다.**
작업자 원칙은 "아주 극소수의 예외를 제외하고 모두 서로서로 존댓말"이고, 그 위에서
**캐릭터에 따라 말투가 결정된다.** 캐릭터를 파악하는 데 드는 시간이 상당하고, 그
파악이 없으면 여러 작업자의 자막이 한 작품처럼 읽히지 않는다.

`terms.py`가 용어 조사에서 한 것과 같은 판단이다 — **번역을 대신하지 않고 조사를
대신한다.**

    ① 뽑는다     자막에서 인물·대사 수·말투·서로 부르는 호칭을 긁는다
    ② 확인한다   외부 자료(공식 페이지·팬덤)에서 성격과 사진을 채운다
    ③ 남긴다     못 채운 것은 '확인 필요'로 두고 근거를 함께 적는다

## 파일이 증명하는 것과 못 하는 것

    자막 안에서 알 수 있다   -> 자동으로 채운다
      인물 목록, 대사 수, 처음 나온 자리, 화자별 말투, 서로 부르는 호칭

    자막이 증명하지 못한다   -> 빈 칸으로 두고 표시한다
      성격, 사진, 그리고 **관계**

관계를 자동으로 단정하지 않는 이유가 있다. `T17`(같은 관계에서 존댓말·반말 혼용)을
계산하려면 **누가 누구에게 말하는지**를 알아야 하는데 자막에는 상대가 표시되지
않는다. 같은 인물이 존댓말과 반말을 섞는 것은 상대가 다르면 정상이므로, 상대를
모르는 채로 지적하면 오답이 된다. 그래서 T17은 이 문서가 관계를 담은 뒤에 성립한다.

호칭은 다르다. `민수 씨`, `선배`, `형`은 **대사 안에 있으므로** 근거가 된다. 관계를
단정하지는 않되 사람이 관계를 적을 때 쓸 재료로 낸다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import formality
from .checks import SPEAKER_ID_RE
from .model import Event
from .text import strip_tags

# 이름 뒤에 붙어 관계를 드러내는 호칭. 자료에서 쓰임이 갈리는 것들이라 그대로 낸다
# (작업자 자료 658행: 다큐·리얼리티에서는 `~씨`를 쓰지 않는다, 드라마에선 가능).
ADDRESS = ("씨", "님", "선배", "후배", "형", "누나", "오빠", "언니", "군", "양",
           "선생님", "사장님", "박사님", "교수님", "아저씨", "아줌마")

# 대괄호·소괄호로 싸인 것은 대사가 아니다.
_MARKUP = re.compile(r"[\[(][^)\]]*[\])]|\{[^}]*\}|♪+")


@dataclass
class Character:
    """등장인물 한 사람. **조연·단역도 뺴지 않는다** — 빠진 인물이 말투 불일치가 된다."""

    name: str                                        # 자막에 적힌 표시
    lines: int = 0                                   # 대사 수
    first_at: int = 0                                # 처음 나온 자막 번호
    first_ms: int = 0                                # 처음 나온 시각
    speech: dict = field(default_factory=dict)       # 말투 집계 (formality.summary)
    calls: dict[str, list[str]] = field(default_factory=dict)   # 상대 -> 쓴 호칭
    mentions: dict[str, int] = field(default_factory=dict)      # 상대 -> 언급 횟수

    # 아래는 자막이 증명하지 못한다. 외부 조사나 사람이 채운다.
    traits: str = ""                                 # 성격
    relations: dict[str, str] = field(default_factory=dict)     # 상대 -> 관계
    photo: str = ""                                  # 로컬 사진 경로
    origin: str = ""                                 # 근거 — 어디서 온 정보인지

    @property
    def dominant(self) -> str:
        """확정된 말투 중 많은 쪽. 확정된 것이 없으면 빈 문자열."""
        counts = (self.speech or {}).get("counts") or {}
        if not any(counts.values()):
            return ""
        return max(counts, key=lambda level: counts[level])

    @property
    def researched(self) -> bool:
        """외부 조사가 채워졌는지. 근거 없이 채운 것은 조사로 보지 않는다."""
        return bool(self.traits) and self.origin not in ("", "모델 제안")


def _body(line: str) -> str:
    """화자 표시를 뗀 대사. 화자 표시가 없으면 줄 전체."""
    found = SPEAKER_ID_RE.match(strip_tags(line))
    return found.group(2) if found and found.group(2).strip() else strip_tags(line)


def extract(events: list[Event]) -> tuple[list[Character], dict]:
    """자막에서 인물을 뽑는다. (인물 목록, 집계)

    **화자 표시가 붙은 자막만 인물에게 돌린다.** 표시가 없는 자막은 앞 화자가
    이어 말하는 것일 수도 있고 표시를 생략한 다른 인물일 수도 있어, 이어 붙이면
    말투 집계가 틀린 인물에게 쌓인다. 몇 건을 못 셌는지는 함께 낸다.
    """
    found: dict[str, Character] = {}
    owned: dict[str, list[Event]] = {}
    untagged = 0

    for ev in events:
        names = []
        for line in ev.lines:
            m = SPEAKER_ID_RE.match(strip_tags(line))
            if m and m.group(2).strip():
                names.append(m.group(1).strip())
        if not names:
            if _MARKUP.sub(" ", strip_tags(ev.text)).strip():
                untagged += 1        # 대사가 있는데 화자를 모르는 것만 센다
            continue
        for name in names:
            who = found.get(name)
            if who is None:
                who = found[name] = Character(name=name, first_at=ev.index,
                                              first_ms=ev.start_ms)
                owned[name] = []
            who.lines += 1
            owned[name].append(ev)

    # 말투는 그 인물의 대사만 모아서 센다.
    for name, evs in owned.items():
        bodies = [Event(e.index, e.start_ms, e.end_ms,
                        "\n".join(_body(ln) for ln in e.lines)) for e in evs]
        found[name].speech = formality.summary(bodies)

    _cross_reference(found, owned)

    # 대사가 많은 순. 주연·조연을 기계가 이름 붙이지 않는다 — 횟수는 사실이고
    # 역할은 판단이다. 사람이 문서에서 적는다.
    people = sorted(found.values(), key=lambda c: (-c.lines, c.first_at))
    return people, {
        "total": len(people),
        "tagged_events": sum(c.lines for c in people),
        "untagged_events": untagged,
    }


def _cross_reference(found: dict[str, Character],
                     owned: dict[str, list[Event]]) -> None:
    """누가 누구를 언급하고 어떤 호칭으로 부르는지 채운다.

    **관계를 단정하지 않는다.** `민수 씨`라고 불렀다는 사실만 적는다 — 존댓말 관계로
    보이지만 비꼬는 말일 수도 있고 상황에 따라 바뀐다. 판단은 사람이 한다.
    """
    names = sorted(found, key=len, reverse=True)     # 긴 이름부터 — `김 경위`가 `경위`에 먹히지 않게
    for speaker, evs in owned.items():
        me = found[speaker]
        for ev in evs:
            body = " ".join(_body(ln) for ln in ev.lines)
            for other in names:
                if other == speaker or other not in body:
                    continue
                me.mentions[other] = me.mentions.get(other, 0) + 1
                for form in ADDRESS:
                    # 이름 바로 뒤(공백은 있어도 된다)에 붙은 호칭만 본다.
                    if re.search(rf"{re.escape(other)}\s*{form}\b", body):
                        used = me.calls.setdefault(other, [])
                        if form not in used:
                            used.append(form)


def to_tsv(people: list[Character]) -> str:
    """표로 낸다. KNP 시트처럼 그대로 붙일 수 있게 탭으로 가른다.

    근거를 칸으로 두는 것은 KNP 관례를 따른 것이다 — 출처 없는 정보는 감수에서
    되돌아온다.
    """
    head = ["이름", "대사 수", "처음", "말투", "합니다체", "해요체", "유보",
            "부르는 호칭", "관계", "성격", "사진", "근거"]
    rows = ["\t".join(head)]
    for who in people:
        counts = (who.speech or {}).get("counts") or {}
        calls = "; ".join(f"{k}->{'/'.join(v)}" for k, v in who.calls.items())
        relations = "; ".join(f"{k}: {v}" for k, v in who.relations.items())
        rows.append("\t".join([
            who.name, str(who.lines), f"#{who.first_at}",
            who.dominant or "확인 필요",
            str(counts.get("합니다체", 0)), str(counts.get("해요체", 0)),
            str((who.speech or {}).get("undecided", 0)),
            calls, relations,
            who.traits.replace("\t", " ") or "확인 필요",
            who.photo, who.origin or "확인 필요",
        ]))
    return "\n".join(rows)


def to_markdown(people: list[Character], counts: dict, title: str = "") -> str:
    """사람이 읽는 문서. 사진을 붙일 수 있어야 하므로 표만으로는 안 된다.

    **사진은 링크로만 넣는다.** 저작권물이므로 납품 문서에 동봉할지는 작업자가
    정한다 — 출처를 함께 적어 판단할 수 있게 한다.
    """
    out = [f"# 캐릭터 분석 — {title}" if title else "# 캐릭터 분석", ""]
    out.append(f"인물 {counts['total']}명 · 화자 표시가 붙은 자막 "
               f"{counts['tagged_events']}개")
    if counts["untagged_events"]:
        # 못 센 것을 숨기지 않는다. 집계가 무엇 위에서 나온 것인지 알아야 한다.
        out.append(f"화자를 모르는 자막 {counts['untagged_events']}개는 집계에서 "
                   f"뺐습니다 — 앞 화자가 이어 말하는 것일 수도 있어 이어 붙이면 "
                   f"말투가 틀린 인물에게 쌓입니다.")
    out.append("")
    out.append("말투는 자막에서 센 것입니다. **관계·성격·사진은 자막이 증명하지 "
               "못하므로 비워 두었습니다.**")
    out.append("")

    for who in people:
        speech = who.speech or {}
        counts_by = speech.get("counts") or {}
        out.append(f"## {who.name}")
        out.append("")
        if who.photo:
            out.append(f"![{who.name}]({who.photo})")
            out.append("")
        out.append(f"- 대사 {who.lines}개 · 처음 나온 자막 #{who.first_at}")
        ratio = speech.get("formal_ratio")
        tone = (f"{who.dominant} (합니다체 {counts_by.get('합니다체', 0)} / "
                f"해요체 {counts_by.get('해요체', 0)}"
                + (f", 합니다체 {ratio:.0%}" if ratio is not None else "")
                + f", 유보 {speech.get('undecided', 0)})") if who.dominant else \
               "확정된 종결어미가 없어 말투를 재지 못했습니다"
        out.append(f"- 말투: {tone}")
        if who.calls:
            out.append("- 부르는 호칭: "
                       + ", ".join(f"{k}에게 '{'/'.join(v)}'"
                                   for k, v in who.calls.items()))
        if who.mentions:
            top = sorted(who.mentions.items(), key=lambda kv: -kv[1])[:5]
            out.append("- 함께 나오는 인물: "
                       + ", ".join(f"{k}({n})" for k, n in top))
        out.append(f"- 관계: {'; '.join(f'{k}: {v}' for k, v in who.relations.items()) or '확인 필요'}")
        out.append(f"- 성격: {who.traits or '확인 필요'}")
        out.append(f"- 근거: {who.origin or '확인 필요'}")
        out.append("")
    return "\n".join(out)


def summarize(people: list[Character]) -> dict:
    return {
        "total": len(people),
        "researched": sum(1 for c in people if c.researched),
        "no_relation": sum(1 for c in people if not c.relations),
        "tone_unknown": sum(1 for c in people if not c.dominant),
    }
