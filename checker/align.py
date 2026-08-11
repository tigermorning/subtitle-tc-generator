"""스크립트와 전사를 맞춰 붙인다.

**어느 쪽도 정답으로 두지 않는다.**

처음에는 "스크립트가 있으면 전사는 버리고 타임코드만 쓴다"고 설계했다가 사용자
지적으로 바로잡았다 — 스크립트도 틀리거나 빠진 데가 많다. 즉흥 대사가 통째로
빠져 있거나, 촬영 중 바뀐 대사가 반영되지 않았거나, 화자 표기만 있고 대사가 없는
경우가 실제로 흔하다.

그래서 이 모듈은 둘을 **대조**한다.

    스크립트와 전사가 비슷하다        -> 스크립트 문장을 쓴다(표기·문장부호가 정돈돼 있다)
    소리는 있는데 스크립트에 없다      -> 전사 문장을 넣고 **표시한다**(즉흥 대사일 수 있다)
    스크립트에 있는데 소리가 없다      -> 자막을 만들지 않고 **표시한다**(잘린 대사일 수 있다)
    비슷하긴 한데 많이 다르다          -> 스크립트를 쓰되 **표시한다**(대사가 바뀌었을 수 있다)

표시한 자리는 사람이 본다. 기계가 어느 쪽이 맞다고 정하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

WORD = re.compile(r"[0-9A-Za-z가-힣]+")


def normalize(text: str) -> list[str]:
    """비교용 토큰. 문장부호·대소문자·표기 차이를 지운다."""
    return [w.lower() for w in WORD.findall(text)]


def similarity(a: str, b: str) -> float:
    ta, tb = normalize(a), normalize(b)
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


@dataclass
class Segment:
    """전사 한 덩어리."""
    start_ms: int
    end_ms: int
    text: str


@dataclass
class AlignedCue:
    start_ms: int
    end_ms: int
    text: str
    source: str            # script | transcript
    similarity: float = 0.0
    note: str = ""         # 사람이 봐야 할 자리에만 채운다

    @property
    def needs_review(self) -> bool:
        return bool(self.note)


def align(segments: list[Segment], script_lines: list[str],
          good_enough: float = 0.6, window: int = 6) -> list[AlignedCue]:
    """전사 세그먼트에 스크립트 줄을 붙인다.

    스크립트는 순서대로 간다고 본다(자막 작업의 대본은 순서가 뒤바뀌지 않는다).
    각 세그먼트에 대해 **아직 안 쓴 스크립트 줄 중 앞쪽 몇 개**만 후보로 본다 —
    전체를 뒤지면 멀리 있는 비슷한 문장에 잘못 붙는다.
    """
    cues: list[AlignedCue] = []
    cursor = 0

    for seg in segments:
        best_index, best_score = -1, 0.0
        for offset in range(window):
            i = cursor + offset
            if i >= len(script_lines):
                break
            score = similarity(seg.text, script_lines[i])
            if score > best_score:
                best_index, best_score = i, score

        if best_index < 0 or best_score < 0.3:
            # 소리는 있는데 스크립트에서 짝을 못 찾았다. 전사를 쓰되, 아직 안 쓴
            # 스크립트 줄이 앞에 있으면 함께 보여 준다 — 대사가 통째로 바뀐 경우
            # "짝이 없다"와 "많이 다르다"를 기계가 가를 수 없기 때문이다.
            note = "스크립트에 없는 대사입니다 — 즉흥 대사이거나 스크립트가 빠졌을 수 있습니다"
            if cursor < len(script_lines):
                note += f" / 이 자리 스크립트: {script_lines[cursor].strip()[:40]}"
            cues.append(AlignedCue(
                seg.start_ms, seg.end_ms, seg.text, "transcript", best_score, note))
            continue

        # 건너뛴 스크립트 줄이 있으면 그것들은 소리를 못 찾은 것이다.
        for skipped in range(cursor, best_index):
            cues.append(AlignedCue(
                seg.start_ms, seg.start_ms, script_lines[skipped], "script", 0.0,
                "이 스크립트 줄에 해당하는 소리를 찾지 못했습니다"
                " — 잘린 대사이거나 지문일 수 있습니다"))

        line = script_lines[best_index]
        note = ""
        if best_score < good_enough:
            note = (f"스크립트와 전사가 많이 다릅니다(유사도 {best_score:.0%})"
                    f" — 전사: {seg.text.strip()[:40]}")
        cues.append(AlignedCue(seg.start_ms, seg.end_ms, line, "script", best_score, note))
        cursor = best_index + 1

    # 뒤에 남은 스크립트 줄
    last_end = segments[-1].end_ms if segments else 0
    for i in range(cursor, len(script_lines)):
        cues.append(AlignedCue(
            last_end, last_end, script_lines[i], "script", 0.0,
            "이 스크립트 줄에 해당하는 소리를 찾지 못했습니다"))

    return cues


def summary(cues: list[AlignedCue]) -> dict:
    """무엇이 어디서 왔고 어디를 봐야 하는지. 조용히 넘어가지 않기 위한 집계다."""
    return {
        "total": len(cues),
        "from_script": sum(1 for c in cues if c.source == "script"),
        "from_transcript": sum(1 for c in cues if c.source == "transcript"),
        "needs_review": sum(1 for c in cues if c.needs_review),
        "no_audio": sum(1 for c in cues if c.start_ms == c.end_ms),
    }
