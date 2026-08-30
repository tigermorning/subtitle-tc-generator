"""SDH 안에 섞인 외국어 대사를 한국어로 옮긴다.

**왜 있나.** 드라마B(디즈니+) E01을 정답 한국어 SDH와 대조해 발견함
(2026-08-30) — 정답은 일본어 대사를 전부 한국어로 옮기고 화자·언어 표시를
붙인다(`[남자가 일어로] 내일 첫 비행기를 타고`). 우리는 일본어를 그대로
전사만 해서 냈다. 대조로 확정된 사실이지 추정이 아니다.

**이 모듈이 하지 않는 것.**
- 화자 이름을 지어내지 않는다(규칙 3) — 대본도 diarize도 없어서 누가
  말하는지 모른다. `[일본어]`처럼 **언어만** 표시한다. 정답의 `[마츠다가
  한국어로]`처럼 이름을 넣는 것은 사람이 나중에 채운다.
- 번역을 확정으로 내지 않는다. 이 방향(일본어·영어 -> 한국어)은 이 프로젝트가
  한 번도 검증한 적이 없다(지금까지는 한국어 -> 다른 언어만 썼다, `translate.py`).
  그래서 옮긴 자리마다 `notes`에 "확인 필요"를 남긴다 — 봐야 할 자리로
  표시하지, 끝난 것으로 위장하지 않는다.
- 오탐(whisper가 한국어를 다른 언어로 잘못 들은 것)까지 번역하면 오류
  위에 오류를 덧씌운다. 그래서 **텍스트를 지어내지 않는다** — 번역기에게
  "모르겠으면 원문 그대로 두라"고 명시한다.
"""

from __future__ import annotations

import re

from .model import Event
from .text import has_hangul, strip_tags

_HIRAGANA_KATAKANA = re.compile(r"[぀-ゟ゠-ヿ]")
_LATIN = re.compile(r"[A-Za-z]")


def detect_language_label(text: str) -> str:
    """대사가 어느 문자 체계인지 어림한다. **낱말만 보고 판정한다** — 안다고
    말할 수 있는 만큼만 말한다(규칙 3). 가나가 있으면 일본어, 라틴 문자만
    있으면 영어, 그 외(주로 한자만)는 뭉뚱그려 외국어로 남긴다.
    """
    if _HIRAGANA_KATAKANA.search(text):
        return "일본어"
    if _LATIN.search(text):
        return "영어"
    return "외국어"


SYSTEM = (
    "You translate a single subtitle line into natural, colloquial Korean. "
    "The line is dialogue spoken in a Korean-language drama by a character "
    "who is speaking a foreign language for this one line. "
    "Reply with ONLY the Korean translation, nothing else — no quotes, no "
    "explanation, no romanization. "
    "If the line is nonsense, garbled, or you cannot make out a real "
    "sentence, reply with exactly UNCLEAR instead of guessing."
)


def translate_foreign_dialogue(events: list[Event], translator,
                               progress=None) -> tuple[list[Event], list[tuple[int, str]]]:
    """외국어로 보이는 자막을 한국어로 옮기고 언어 표시를 붙인다.

    돌려주는 `notes`는 `Draft.notes`에 그대로 이어 붙일 수 있다 — 옮긴 자리마다
    "확인 필요"를 남긴다(위 모듈 설명 참고). 번역기가 `UNCLEAR`를 돌려주면
    **원문을 그대로 둔다** — 지어내지 않는다(규칙 4).
    """
    say = progress or (lambda _m: None)
    if translator is None:
        return events, []

    # 한글이 하나도 없고 글자(자모 포함)가 있는 자막만 대상이다.
    targets = [ev for ev in events
              if not has_hangul(strip_tags(ev.text)) and any(ch.isalpha() for ch in ev.text)]
    if not targets:
        return events, []

    say(f"외국어 대사 {len(targets)}곳을 한국어로 옮깁니다(초안 — 확인 필요)...")
    target_ids = {ev.index for ev in targets}
    notes: list[tuple[int, str]] = []
    out: list[Event] = []
    for ev in events:
        if ev.index not in target_ids:
            out.append(ev)
            continue
        label = detect_language_label(ev.text)
        original = ev.text
        translated = translator.ask(SYSTEM, original).strip()
        if not translated or translated.upper() == "UNCLEAR":
            out.append(ev)  # 원문 그대로 둔다 — 지어내지 않는다
            notes.append((ev.index, f"{label} 대사로 보이나 번역하지 못했습니다."
                                    " 영상에서 직접 확인하세요."))
            continue
        new_text = f"[{label}] {translated}"
        out.append(Event(ev.index, ev.start_ms, ev.end_ms, new_text))
        notes.append((ev.index, f"{label} 대사를 한국어로 옮긴 초안입니다 — 확인 필요"
                               f"(원문: {original})"))
    return out, notes
