"""자막을 의미 단위로 다시 나누고 타임코드를 배분한다.

**글자 수는 마지막에 맞춘다.** whisper의 `max_len`으로 전사 단계에서 글자 수를
자르면 문장이 부서진 채로 굳는다. 사람이 하는 순서가 옳다.

    1. 전사는 글자 수를 무시하고 자연스럽게        (whisper)
    2. 스크립트와 대조해 텍스트를 정한다            (align.py)
    3. **의미 단위로 다시 끊고 스포팅을 재배치한다** (여기)
    4. 글자 수·읽기 속도를 맞춘다                   (timing.py, checks)

**번역 자막에서는 원어에 이 규칙을 적용하지 않는다.** 16자·읽기 속도는 한국어
기준이고, 원어 스크립트는 번역을 위한 작업 재료일 뿐 납품물이 아니다. 원어의 글자
수나 스포팅을 맞추느라 시간을 쓰면 헛일이고, 원어 기준으로 끊어 놓으면 한국어가
거기에 갇힌다. **재분할은 번역이 끝난 뒤 한국어에 대해서만** 한다.

이 모듈은 3단계다. 끊는 자리를 고를 때 우선순위:

    ① 문장이 끝나는 자리      . ? ! 뒤
    ② 절이 끊기는 자리        쉼표·접속 어미 뒤
    ③ 말소리가 쉬는 자리      구간 사이 침묵(있으면)
    ④ 어절 경계              그 외

시간은 글자 수 비율로 나눈다. 말이 고르게 나오지 않으므로 정확하지 않지만,
말소리 구간을 주면 그 경계에 맞춰 보정한다.
"""

from __future__ import annotations

import re

from .model import Event
from .text import count_chars

SENTENCE_END = re.compile(r"(?<=[.?!。？！])\s+")
# 파이썬 정규식의 lookbehind는 길이가 같아야 한다. 어미 목록은 길이가 제각각이라
# lookbehind로 못 쓴다 — 어절을 잡아 그 끝을 끊는 자리로 삼는다.
CLAUSE_END = re.compile(r"[,;、]\s+|(?:고|며|는데|지만|면서|다가|거나)\s+")


def _split_points(text: str) -> list[int]:
    """끊을 수 있는 자리를 우선순위 순으로 돌려준다(문자 위치)."""
    points: list[tuple[int, int]] = []   # (우선순위, 위치)
    for m in SENTENCE_END.finditer(text):
        points.append((0, m.start()))
    for m in CLAUSE_END.finditer(text):
        # 부호·어미 **뒤**에서 끊는다
        points.append((1, m.end() - len(m.group(0)) + len(m.group(0).rstrip())))
    for m in re.finditer(r"\s+", text):
        points.append((2, m.start()))
    points.sort(key=lambda p: (p[0], abs(p[1] - len(text) / 2)))
    return [pos for _rank, pos in points]


def split_text(text: str, max_chars: float, weights: dict | None = None) -> list[str]:
    """`max_chars`를 넘지 않게 의미 단위로 자른다.

    가운데에 가까운 자리를 고른다 — 한쪽만 길게 남으면 다음 조각이 또 잘려야 한다.
    """
    text = text.strip()
    if not text or count_chars(text, weights) <= max_chars:
        return [text] if text else []

    for pos in _split_points(text):
        left, right = text[:pos].strip(), text[pos:].strip()
        if not left or not right:
            continue
        if count_chars(left, weights) <= max_chars:
            return [left] + split_text(right, max_chars, weights)

    # 끊을 자리가 없다(한 어절이 너무 길다). 자르지 않고 그대로 둔다 —
    # 억지로 글자 중간을 자르면 말이 깨진다. 검사가 길다고 잡아 줄 것이다.
    return [text]


def _allocate(start_ms: int, end_ms: int, pieces: list[str],
              weights: dict | None = None) -> list[tuple[int, int]]:
    """글자 수 비율로 시간을 나눈다."""
    sizes = [max(count_chars(p, weights), 0.5) for p in pieces]
    total = sum(sizes)
    spans: list[tuple[int, int]] = []
    cursor = start_ms
    for i, size in enumerate(sizes):
        share = (end_ms - start_ms) * size / total
        piece_end = end_ms if i == len(sizes) - 1 else int(round(cursor + share))
        spans.append((int(round(cursor)), piece_end))
        cursor = piece_end
    return spans


def _snap_to_silence(spans: list[tuple[int, int]],
                     speech: list[tuple[int, int]] | None,
                     tolerance_ms: int = 400) -> list[tuple[int, int]]:
    """조각 경계를 가까운 침묵으로 당긴다. 말 한가운데서 끊기지 않게."""
    if not speech or len(spans) < 2:
        return spans

    gaps = [(a_end, b_start) for (_, a_end), (b_start, _) in zip(speech, speech[1:])]
    out = list(spans)
    for i in range(len(out) - 1):
        boundary = out[i][1]
        best = None
        for gap_start, gap_end in gaps:
            middle = (gap_start + gap_end) // 2
            if abs(middle - boundary) <= tolerance_ms and (best is None
                                                           or abs(middle - boundary) < abs(best - boundary)):
                best = middle
        if best is not None and out[i][0] < best < out[i + 1][1]:
            out[i] = (out[i][0], best)
            out[i + 1] = (best, out[i + 1][1])
    return out


def resplit(event: Event, max_chars_per_cue: float,
            weights: dict | None = None,
            speech: list[tuple[int, int]] | None = None) -> list[Event]:
    """자막 하나를 여러 개로 나눈다. 나눌 필요가 없으면 그대로 돌려준다."""
    pieces = split_text(event.text, max_chars_per_cue, weights)
    if len(pieces) <= 1:
        return [event]

    spans = _snap_to_silence(_allocate(event.start_ms, event.end_ms, pieces, weights),
                             speech)
    return [Event(event.index, s, e, text) for (s, e), text in zip(spans, pieces)]


def resplit_all(events: list[Event], profile: dict,
                speech: list[tuple[int, int]] | None = None,
                origins: list[int] | None = None) -> list[Event]:
    """전체를 다시 나누고 번호를 다시 매긴다.

    한 자막이 담을 수 있는 글자 수는 **한 줄 한계 × 줄 수**다. 줄바꿈은 이 뒤에
    `korean_break`가 보는 문제이고, 여기서는 자막 단위만 정한다.

    `origins`를 주면 새 자막마다 **원래 번호**를 채워 준다. 번호를 다시 매기면
    앞 단계에서 표시해 둔 "봐야 할 자리"가 엉뚱한 자막을 가리키기 때문이다.
    """
    limits = profile.get("limits") or {}
    per_line = limits.get("chars_per_line") or 42
    max_lines = limits.get("max_lines") or 2
    weights = limits.get("char_weights")

    out: list[Event] = []
    for ev in events:
        pieces = resplit(ev, per_line * max_lines, weights, speech)
        out.extend(pieces)
        if origins is not None:
            origins.extend([ev.index] * len(pieces))
    for i, ev in enumerate(out, 1):
        ev.index = i
    return out
