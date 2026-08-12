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
from pathlib import Path

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
    #
    # **항목을 지어낸 것이 아니다.** 작업자 자료가 무엇을 봐야 하는지 적어 두었다:
    #   "인물 성격 파악에 따른 말투, 단어 설정이 중요함. … 모든 인물들의 말투가
    #    번역가의 말투로 설정되었다는 뜻이기 때문에 좋은 번역이 아님.
    #    (ex.) 성별, 나이, 직업, 경력, 싸가지 없는 성격, 비꼬기 좋아하는 성격 등"
    # **사람이 정하는 말투.** 잰 말투(`speech`)와 다르다 — 잰 것은 자막이 지금 어떤지고,
    # 이것은 그 인물이 어떠해야 하는지다. T17(말투 혼용) 검사가 이 칸을 본다.
    #
    # 이 칸이 없으면 T17을 돌 수 없다. 같은 인물이 존댓말과 반말을 섞는 것은 **상대가
    # 다르면 정상**이고, 자막에 상대는 표시되지 않는다. 그래서 "이 인물은 이렇게
    # 말한다"를 사람이 적어 주어야 어긋난 자리를 가릴 수 있다.
    declared_tone: str = ""                          # 합니다체 | 해요체 | 반말
    gender: str = ""                                 # 성별
    age: str = ""                                    # 나이
    job: str = ""                                    # 직업
    career: str = ""                                 # 경력 (소속·계급 등)
    family: str = ""                                 # 가족 관계
    traits: str = ""                                 # 성격
    relations: dict[str, str] = field(default_factory=dict)     # 상대 -> 관계
    photo: str = ""                                  # 로컬 사진 경로 또는 주소
    photo_licence: str = ""                          # 사진 라이선스 — 동봉 판단 재료
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
        """외부 조사가 채워졌는지. **근거 없이 채운 것은 조사로 보지 않는다.**"""
        filled = any((self.gender, self.age, self.job, self.career, self.traits))
        return filled and self.origin not in ("", "모델 제안")

    @property
    def missing(self) -> list[str]:
        """아직 비어 있는 항목. 문서에 '확인 필요'로 나갈 것들."""
        labels = {"gender": "성별", "age": "나이", "job": "직업",
                  "career": "경력", "traits": "성격"}
        return [name for key, name in labels.items() if not getattr(self, key)]


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


def research(people: list[Character], wiki: str, work_title: str = "",
             limit: int = 0, with_image: bool = True, progress=None) -> dict:
    """외부 자료에서 성격·사진을 채운다. **기본으로 돌지 않는다** — 부르는 쪽이 켠다.

    나가는 것은 **작품 제목과 인물 이름뿐**이다. 대사·대본은 어떤 경우에도 나가지
    않는다(규칙 6). 무엇을 보냈는지 돌려주는 사전의 `sent`에 담아 낸다.

    `wiki`는 **사람이 지정한다.** 슬러그를 짐작하면 엉뚱한 작품의 위키를 읽고, 엉뚱한
    인물 정보는 없는 것보다 나쁘다 — `terms.py`가 "못 찾은 것을 지어내지 않는다"고
    한 것과 같은 판단이다.

    `limit`을 주면 대사가 많은 인물부터 그만큼만 조사한다. 단역까지 다 부르면 요청이
    수십 번 나가고, 단역은 위키에 문서가 없는 것이 보통이다.
    """
    from . import webchars

    say = progress or (lambda _m: None)
    webchars.forget()
    targets = people[:limit] if limit else list(people)
    found = 0

    for who in targets:
        try:
            hit = webchars.lookup(wiki, who.name, work_title, with_image=with_image)
        except Exception as exc:            # 네트워크·형식 문제로 조사가 멈추면 안 된다
            say(f"조사 실패({who.name}): {exc}")
            continue
        if hit is None:
            say(f"문서를 못 찾았습니다: {who.name}")
            continue

        who.gender = who.gender or hit.fields.get("gender", "")
        who.age = who.age or hit.fields.get("age", "")
        who.job = who.job or hit.fields.get("job", "")
        who.career = who.career or hit.fields.get("career", "")
        who.family = who.family or hit.fields.get("family", "")
        # **성격은 인포박스에 없다.** 소개 문단이 유일한 재료이고 그것도 요약이라
        # 그대로 성격이라고 부를 수 없다. 원문을 그대로 두고 사람이 읽게 한다.
        who.traits = who.traits or hit.summary
        who.photo = who.photo or hit.image_url
        who.photo_licence = who.photo_licence or hit.image_licence
        # 후보가 여럿이었으면 그 사실을 근거에 남긴다 — 엉뚱한 인물일 수 있다.
        who.origin = hit.url + (" (후보가 여럿이라 확인 필요)" if hit.ambiguous else "")
        found += 1
        say(f"{who.name}: {', '.join(k for k in hit.fields) or '칸 없음'}")

    sent = webchars.sent()
    say(f"인물 {len(targets)}명 중 {found}명을 찾았습니다. "
        f"밖으로 보낸 것 {len(sent)}건(작품 제목과 인물 이름뿐)")
    return {"looked_up": len(targets), "found": found, "sent": sent, "wiki": wiki}


def to_tsv(people: list[Character]) -> str:
    """표로 낸다. KNP 시트처럼 그대로 붙일 수 있게 탭으로 가른다.

    근거를 칸으로 두는 것은 KNP 관례를 따른 것이다 — 출처 없는 정보는 감수에서
    되돌아온다.
    """
    head = ["이름", "대사 수", "처음", "말투", "말투 지정", "합니다체", "해요체", "유보",
            "부르는 호칭", "관계",
            # 아래 다섯은 작업자 자료가 이름 붙인 항목이다(성별·나이·직업·경력·성격).
            "성별", "나이", "직업", "경력", "성격",
            "사진", "사진 라이선스", "근거"]
    rows = ["\t".join(head)]
    for who in people:
        counts = (who.speech or {}).get("counts") or {}
        calls = "; ".join(f"{k}->{'/'.join(v)}" for k, v in who.calls.items())
        relations = "; ".join(f"{k}: {v}" for k, v in who.relations.items())

        def cell(value: str) -> str:
            # 탭이 들어가면 칸이 밀린다. 빈 칸은 '확인 필요'로 둔다 — 빈칸은 지나치고
            # 글자는 눈에 띈다(규칙 3과 같은 판단).
            return (value or "확인 필요").replace("\t", " ").replace("\n", " ")

        rows.append("\t".join([
            who.name, str(who.lines), f"#{who.first_at}",
            who.dominant or "확인 필요",
            # **비워 두면 T17이 돌지 않는다.** 채우라고 적어 둔다.
            who.declared_tone or "정해 주세요",
            str(counts.get("합니다체", 0)), str(counts.get("해요체", 0)),
            str((who.speech or {}).get("undecided", 0)),
            calls, relations,
            cell(who.gender), cell(who.age), cell(who.job), cell(who.career),
            cell(who.traits),
            who.photo,
            # **사진이 있는데 라이선스를 모르면 그렇게 적는다.** 비워 두면 자유
            # 이용으로 오해할 수 있고, 그 오해가 납품 문서에 실린다.
            (who.photo_licence or "확인 필요") if who.photo else "",
            who.origin or "확인 필요",
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
            # **라이선스를 사진 옆에 붙인다.** 문서를 보는 사람이 동봉 여부를 그
            # 자리에서 판단할 수 있어야 한다.
            out.append("")
            out.append(f"사진 출처: {who.photo} · 라이선스: "
                       f"{who.photo_licence or '확인 필요'}")
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
        # 작업자 자료가 이름 붙인 항목들. 빈 것은 '확인 필요'로 남긴다.
        for label, value in (("성별", who.gender), ("나이", who.age),
                             ("직업", who.job), ("경력", who.career),
                             ("가족", who.family)):
            if value:
                out.append(f"- {label}: {value}")
        out.append(f"- 성격: {who.traits or '확인 필요'}")
        if who.missing:
            out.append(f"- 아직 빈 항목: {', '.join(who.missing)}")
        out.append(f"- 근거: {who.origin or '확인 필요'}")
        out.append("")

    out.append("---")
    out.append("")
    out.append("성격 칸은 위키 소개 문단을 **그대로** 옮긴 것입니다. 요약이므로 "
               "성격 자체는 아닙니다 — 읽고 고쳐 쓰십시오.")
    out.append("")
    out.append("사진은 **주소만** 적었습니다. 저작권물이므로 납품 문서에 동봉할지는 "
               "라이선스를 보고 판단하십시오.")
    return "\n".join(out)


PLACEHOLDERS = {"확인 필요", "정해 주세요", "-", "—", ""}


def read_tsv(path: Path) -> list[Character]:
    """작업자가 채운 시트를 되읽는다. **칸 순서가 아니라 머리글로 찾는다.**

    사람이 엑셀에서 칸을 옮기거나 칸을 더 붙이는 것이 실제로 일어난다. 순서로 읽으면
    그때 조용히 엉뚱한 값이 들어온다.

    `확인 필요`·`정해 주세요` 같은 자리표시자는 **빈 값으로 읽는다** — 우리가 적어 낸
    글자를 사람이 채운 것으로 착각하면 안 된다.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    rows = [line.split("\t") for line in text.splitlines() if line.strip()]
    if not rows:
        return []

    head = [h.strip() for h in rows[0]]
    index = {name: i for i, name in enumerate(head)}

    def cell(row: list[str], name: str) -> str:
        i = index.get(name)
        if i is None or i >= len(row):
            return ""
        value = row[i].strip()
        return "" if value in PLACEHOLDERS else value

    people: list[Character] = []
    for row in rows[1:]:
        name = cell(row, "이름")
        if not name:
            continue
        who = Character(name=name)
        who.declared_tone = _tone_of(cell(row, "말투 지정"))
        who.gender = cell(row, "성별")
        who.age = cell(row, "나이")
        who.job = cell(row, "직업")
        who.career = cell(row, "경력")
        who.traits = cell(row, "성격")
        who.photo = cell(row, "사진")
        who.photo_licence = cell(row, "사진 라이선스")
        who.origin = cell(row, "근거")
        for pair in cell(row, "관계").split(";"):
            key, _, value = pair.partition(":")
            if key.strip() and value.strip():
                who.relations[key.strip()] = value.strip()
        try:
            who.lines = int(cell(row, "대사 수") or 0)
        except ValueError:
            who.lines = 0
        people.append(who)
    return people


# 사람이 적는 말이 한 가지일 리 없다. 같은 뜻으로 쓰는 것들을 받아 준다 —
# **모르는 말이 오면 빈 값으로 둔다**(짐작해서 한쪽으로 떨어뜨리지 않는다).
TONE_WORDS = {
    "합니다체": ("합니다체", "하십시오체", "격식체", "격식"),
    "해요체": ("해요체", "비격식", "두루높임"),
    "반말": ("반말", "해체", "낮춤", "해라체", "평어"),
}


def _tone_of(word: str) -> str:
    word = (word or "").strip().replace(" ", "")
    for level, spellings in TONE_WORDS.items():
        if word in spellings:
            return level
    return ""


def summarize(people: list[Character]) -> dict:
    return {
        "total": len(people),
        "researched": sum(1 for c in people if c.researched),
        "no_relation": sum(1 for c in people if not c.relations),
        "tone_unknown": sum(1 for c in people if not c.dominant),
    }
