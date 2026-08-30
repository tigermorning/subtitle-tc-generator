"""전사 원문이 앞뒤 맥락과 맞는지 로컬 LLM으로 확인한다.

whisper는 비슷하게 들리는 다른 말로 잘못 듣고도 문법이 멀쩡한 문장을 만들어
낸다(`transcribe.py` 첫머리 실측: "동기와 설명" vs "동기화 설명", "그 석태들
기본강에서" vs "그 서프트웨어 기본강의에서"). 문장 하나만 보면 이상해 보이지
않아 규칙 4의 "확실한 근거" 검사(문법·형식)로는 못 걸러낸다 — 걸러내려면
**앞뒤 자막과 이어지는지**를 봐야 한다.

이것도 영상에서 들은 소리를 놓고 벌이는 **추정**이다(규칙 4). 그래서 고치지
않고 표시만 한다 — 사람이 영상을 다시 들어 확인한다.
"""

from __future__ import annotations

import re

from .model import Event

SYSTEM = (
    "You review a raw speech-to-text transcript for lines that do not fit "
    "their surrounding context. The transcript is machine-generated and can "
    "mishear a word as a different, similarly-sounding word — the line still "
    "reads as a grammatical sentence, but it contradicts or makes no sense "
    "next to the lines around it.\n"
    "Do not flag: ordinary topic changes, sentences cut short by scene "
    "timing, or lines that are merely awkward but plausible.\n"
    "Reply with only the lines you flag, one per line, as 'N: reason' "
    "(short reason, same language as the transcript). If nothing is "
    "suspicious, reply with the single word NONE."
)

_FLAG = re.compile(r"^\s*(\d+)\s*[:.]\s*(.+)")


def flag_context_mismatches(events: list[Event], translator, batch: int = 10,
                            window: int = 3, progress=None) -> list[tuple[int, str]]:
    """자막 번호별 (문맥 불일치 의심 이유) 목록을 돌려준다. 자막을 고치지 않는다."""
    say = progress or (lambda _m: None)
    if translator is None or not events:
        return []

    flags: list[tuple[int, str]] = []
    for start in range(0, len(events), batch):
        chunk = events[start:start + batch]
        say(f"문맥 검사 {start + 1}~{start + len(chunk)} / {len(events)}")

        before = events[max(0, start - window):start]
        after = events[start + len(chunk):start + len(chunk) + window]
        context = ""
        if before:
            context += "Before:\n" + "\n".join(f"  {e.text}" for e in before) + "\n"
        if after:
            context += "After:\n" + "\n".join(f"  {e.text}" for e in after) + "\n"

        lines = "\n".join(f"{e.index}. {e.text}" for e in chunk)
        reply = translator.ask(SYSTEM, f"{context}\nLines to review:\n{lines}").strip()
        if not reply or reply.upper() == "NONE":
            continue

        valid = {e.index for e in chunk}
        for line in reply.splitlines():
            found = _FLAG.match(line)
            if not found:
                continue
            index = int(found.group(1))
            if index in valid:
                flags.append((index, found.group(2).strip()))
    return flags
