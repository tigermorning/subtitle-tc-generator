"""자막을 의미 단위로 다시 나누고 타임코드를 배분한다.

**글자 수는 마지막에 맞춘다.** whisper의 `max_len`으로 전사 단계에서 글자 수를
자르면 문장이 부서진 채로 굳는다. 사람이 하는 순서가 옳다.

    1. 전사는 글자 수를 무시하고 자연스럽게        (whisper)
    2. 스크립트와 대조해 텍스트를 정한다            (align.py)
    3. **의미 단위로 다시 끊고 스포팅을 재배치한다** (여기)
    4. 글자 수·읽기 속도를 맞춘다                   (timing.py, checks)

**번역 자막에서는 원어에 이 규칙을 적용하지 않는다.** 글자 수·읽기 속도는 한국어
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
from .profile import load_learned_chars_per_cue
from .text import count_chars, strip_tags

SENTENCE_END = re.compile(r"(?<=[.?!。？！])\s+")
# 파이썬 정규식의 lookbehind는 길이가 같아야 한다. 어미 목록은 길이가 제각각이라
# lookbehind로 못 쓴다 — 어절을 잡아 그 끝을 끊는 자리로 삼는다.
#
# **"과정에서"만 통째로 넣는다 — "에서"는 안 된다.** 드라마B E04를
# 정답과 대조해 "과정에서" 뒤에서 절이 갈리는 자리를 2건 찾았다("히로뽕을
# 요구하는 과정에서 / 그들을 무자비하게 살해했습니다", "이들이 범행 과정에서 /
# 살해 결심이 확고했다는 것을 증명합니다" — 둘 다 지금 코드는 한 자막으로
# 뭉친다). 규칙12(최소 2편)의 "여러 편"은 아직 한 회차 안 반복일 뿐 다른
# 작품·회차에서 재현된 게 아니라 엄밀히는 미달이지만, 2026-09-08 사용자가
# 직접 승인해 넣는다. "에서"를 조사 전체로 넣으면 "학교에서 공부한다"처럼
# 흔한 장소 조사와 안 구분돼 정상 문장을 엉뚱하게 쪼갠다(직접 검토 결과,
# CLAUDE.md 규칙13 학습 기록 참고) — 그래서 "과정에서" 이 단어만 좁혀 넣는다.
CLAUSE_END = re.compile(r"[,;、]\s+|(?:고|며|는데|지만|면서|다가|거나|과정에서)\s+")

# **영어 약어 뒤 마침표는 문장 끝이 아니다.** SENTENCE_END는 마침표만 보고 판단해서
# "Mr. Cho" 사이를 문장 경계로 오판한다 — 2026-08-30, 예능A 15·16회 영어 번역
# 실측으로 발견(호칭이 이름과 갈라져 "Mr."만 자막 하나로 남는 사고, 15회 5건·16회
# 1건). `force_sentence_split`(예능 장르, 2026-08-27 추가)이 켜지면 글자 수가
# 남아도 이 자리를 무조건 자르기 때문에 특히 잘 드러난다. 물음표·느낌표는 약어에
# 안 쓰이므로 마침표만 검사한다.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "jr", "sr", "st", "rev", "capt", "lt",
    "col", "gen", "sgt", "fr", "mt", "vs", "etc", "no", "vol", "approx",
}


def _is_real_sentence_end(text: str, punct_pos: int) -> bool:
    """`text[punct_pos]`가 진짜 문장 끝인지 — 영어 약어 뒤 마침표는 아니다."""
    if text[punct_pos] != ".":
        return True
    word = re.search(r"([A-Za-z]+)$", text[:punct_pos])
    return not (word and word.group(1).lower() in _ABBREVIATIONS)


def _split_points(text: str, target_chars: float | None = None) -> list[int]:
    """끊을 수 있는 자리를 우선순위 순으로 돌려준다(문자 위치).

    `target_chars`가 있으면 텍스트 가운데(`len(text) / 2`) 대신 그 글자 수에
    가까운 자리를 우선한다 — 학습값(T14, 실무자가 실제로 고른 자막 길이)이
    있을 때는 그 값을 향해 자른다. `None`이면 기존 동작(가운데 우선)과 100%
    같다.
    """
    points: list[tuple[int, int]] = []   # (우선순위, 위치)
    for m in SENTENCE_END.finditer(text):
        if not _is_real_sentence_end(text, m.start() - 1):
            continue
        points.append((0, m.start()))
    for m in CLAUSE_END.finditer(text):
        # 부호·어미 **뒤**에서 끊는다
        points.append((1, m.end() - len(m.group(0)) + len(m.group(0).rstrip())))
    for m in re.finditer(r"\s+", text):
        points.append((2, m.start()))
    anchor = target_chars if target_chars is not None else len(text) / 2
    points.sort(key=lambda p: (p[0], abs(p[1] - anchor)))
    return [pos for _rank, pos in points]


def split_text(text: str, max_chars: float, weights: dict | None = None,
              force_sentence_split: bool = False,
              force_clause_split: bool = False,
              min_piece_chars: float = 0,
              target_chars: float | None = None) -> list[str]:
    """`max_chars`를 넘지 않게 의미 단위로 자른다.

    가운데에 가까운 자리를 고른다 — 한쪽만 길게 남으면 다음 조각이 또 잘려야 한다.

    `force_sentence_split`이 참이면 **글자 수 안에 들어가도** 문장이 끝나는
    자리(마침표·물음표·느낌표 뒤)가 중간에 있으면 거기서도 자른다. 예능처럼
    빠르게 주고받는 대화는 서로 다른 발화 여러 개가 번역 후에도 글자 수 한도
    안에 들어가는 일이 흔하다(2026-08-27, 예능A 15회 영어 번역 실측 —
    한국어 쪽 병합 개수는 정답 SDH와 거의 같았는데 번역된 영어 최종 자막
    개수는 정답의 79%에 그쳤다. 원인은 병합이 아니라 여기였다). 한 자막에
    서로 다른 발화가 남아 있으면 겉보기엔 안 잘렸어도 정답과는 다른 단위다.

    `force_clause_split`이 참이면 **문장 안 절 경계**(쉼표·접속 어미)에서도
    글자 수와 무관하게 자른다. 2026-08-30, 드라마B E01 정답과의
    단어 단위 대조로 발견: 정답이 자막을 나누는 자리의 44.5%가 whisper
    조각 **안**이었다 — 그런데 그 자리의 말소리 간격은 조각 사이와 다르지
    않았다(간격 0~50ms인 자리조차 7.3%는 정답이 갈랐다). 사람은 절이 끝나도
    쉬지 않고 이어 말하지만 자막은 거기서 가른다는 뜻 — **소리가 아니라
    뜻으로 가르는 자리**라 간격 기반 병합으로는 못 잡는다. `min_piece_chars`
    로 너무 짧은 조각(예: 한 어절짜리 절)까지 쪼개는 것은 막는다 — 그러면
    반대로 정답보다 더 잘게 잘라 새 문제를 만든다.
    """
    text = text.strip()
    if not text:
        return []

    if force_sentence_split or force_clause_split:
        candidates: list[int] = []
        if force_sentence_split:
            candidates += [m.start() for m in SENTENCE_END.finditer(text)
                          if _is_real_sentence_end(text, m.start() - 1)]
        if force_clause_split:
            candidates += [m.end() - len(m.group(0)) + len(m.group(0).rstrip())
                           for m in CLAUSE_END.finditer(text)]
        candidates = sorted(set(candidates))
        for pos in candidates:
            left, right = text[:pos].strip(), text[pos:].strip()
            if not left or not right:
                continue
            if (count_chars(left, weights) < min_piece_chars
                    or count_chars(right, weights) < min_piece_chars):
                continue
            return ([left] if count_chars(left, weights) <= max_chars
                    else split_text(left, max_chars, weights, force_sentence_split,
                                    force_clause_split, min_piece_chars, target_chars)) + \
                   split_text(right, max_chars, weights, force_sentence_split,
                              force_clause_split, min_piece_chars, target_chars)

    if count_chars(text, weights) <= max_chars:
        return [text]

    for pos in _split_points(text, target_chars):
        left, right = text[:pos].strip(), text[pos:].strip()
        if not left or not right:
            continue
        if count_chars(left, weights) <= max_chars:
            return [left] + split_text(right, max_chars, weights, force_sentence_split,
                                       target_chars=target_chars)

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


# 자를 자리를 침묵 쪽으로 당길 때 **얼마나 멀리까지 당기는가**. 2026-08-12에
# 근거 없이 들어온 값이고, 2026-09-08에 처음 실측했다(`tools/vad_sweep.py` —
# 정답 자막의 경계가 실제로 침묵 한가운데에서 얼마나 떨어져 있는지 잰다).
#
#     자료                        중앙값    400ms 안에 드는 경계
#     드라마B E02          764ms    31.5%
#     드라마B E03          582ms    36.1%
#     영화A(영어 애니)        1683ms    20.2%
#
# **즉 이 폭은 경계의 3분의 1 정도만 당긴다.** 나머지는 글자 수 비례로 나눈
# 자리에 그대로 남는다. 넓히면 더 많이 당기겠지만 그만큼 **글자 수 비례 위치에서
# 멀어지는** 대가를 치른다 — 어느 쪽이 정답에 가까운지는 이 숫자만으로는 모른다.
# `--against`로 최종 TC를 견줘 봐야 알 수 있고, 그때도 규칙 12대로 최소 2편이
# 같은 방향을 가리켜야 바꾼다. **그래서 지금은 안 바꿨다.**
#
# 위 거리는 **모든 정답 경계**(인점·아웃점)를 잰 값이라 이 함수가 실제로 다루는
# 자리(자막 하나를 여러 조각으로 나눌 때 생기는 **안쪽** 경계)와 정확히 같지는
# 않다 — 폭의 대략적 크기를 말해 주는 근사치다.
SNAP_TOLERANCE_MS = 400


_CONTENT = re.compile(r"[\w가-힣]", re.UNICODE)


def _content(text: str) -> str:
    """글자 맞추기용 — 공백·문장부호·태그를 뺀 알맹이만."""
    return "".join(_CONTENT.findall(strip_tags(text)))


def _allocate_by_words(start_ms: int, end_ms: int, pieces: list[str],
                       words: list[tuple[int, int, str]]) -> list[tuple[int, int]] | None:
    """조각 경계를 **단어가 실제로 끝난 자리**에 놓는다. 못 맞추면 None.

    글자 수 비례(`_allocate`)는 말의 빠르기가 고르다고 가정한다 — 사람은
    그렇게 말하지 않는다. 정답지 대조(2026-09-11, 드라마B E02·E03)에서
    인점이 100ms 안에 든 것이 38%뿐이었고, 그 경계 대부분이 비례로 놓인 자리였다.
    faster-whisper가 단어마다 시각을 주므로(오차 100ms 안팎이 문헌값 — MFA 같은
    forced aligner는 15ms대. 다음 후보) 조각 텍스트를 단어 열에 맞춰 걷고,
    조각이 끝난 단어의 끝과 다음 단어의 시작 **한가운데**를 경계로 삼는다.

    맞추는 방법은 글자 세기다: 조각의 알맹이 글자 수만큼 단어를 소비한다.
    단어 열의 알맹이가 자막 텍스트와 10% 넘게 다르면(번역·화자명·환각 정리로
    텍스트가 바뀐 자리) None을 돌려주고 비례로 돌아간다 — 틀린 자리에 억지로
    맞추느니 예전 방식이 낫다(규칙 4).
    """
    if not words or len(pieces) < 2:
        return None
    inside = [w for w in words if start_ms - 50 <= (w[0] + w[1]) // 2 <= end_ms + 50]
    if not inside:
        return None
    word_chars = sum(len(_content(w[2])) for w in inside)
    text_chars = sum(len(_content(p)) for p in pieces)
    if not word_chars or not text_chars or abs(word_chars - text_chars) > max(2, text_chars * 0.10):
        return None

    spans: list[tuple[int, int]] = []
    cursor = start_ms
    wi = 0
    consumed = 0        # 지금 단어에서 이미 쓴 글자 수
    for k, piece in enumerate(pieces):
        need = len(_content(piece))
        if k == len(pieces) - 1:
            spans.append((cursor, end_ms))
            break
        while need > 0 and wi < len(inside):
            avail = len(_content(inside[wi][2])) - consumed
            if avail <= need:
                need -= avail
                wi += 1
                consumed = 0
            else:
                consumed += need
                need = 0
        if wi >= len(inside):
            return None
        last_end = inside[wi - 1][1] if consumed == 0 and wi > 0 else inside[wi][1]
        next_start = inside[wi][0] if consumed == 0 else inside[wi][1]
        boundary = (last_end + next_start) // 2 if next_start > last_end else last_end
        boundary = max(cursor + 1, min(boundary, end_ms - 1))
        spans.append((cursor, boundary))
        cursor = boundary
    return spans if len(spans) == len(pieces) else None


def _snap_to_silence(spans: list[tuple[int, int]],
                     speech: list[tuple[int, int]] | None,
                     tolerance_ms: int = SNAP_TOLERANCE_MS) -> list[tuple[int, int]]:
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
            speech: list[tuple[int, int]] | None = None,
            force_sentence_split: bool = False,
            force_clause_split: bool = False,
            min_piece_chars: float = 0,
            clause_split_min_duration_ms: int = 0,
            target_chars: float | None = None,
            words: list[tuple[int, int, str]] | None = None) -> list[Event]:
    """자막 하나를 여러 개로 나눈다. 나눌 필요가 없으면 그대로 돌려준다.

    `words`(단어 시각)가 있으면 조각 경계를 단어가 끝난 자리에 놓는다
    (`_allocate_by_words`). 없거나 못 맞추면 글자 수 비례(`_allocate`).

    `force_clause_split`은 `clause_split_min_duration_ms`보다 **긴** 자막에만
    켠다(2026-08-30, 드라마B E01 재검증 — 짧은 자막까지 무조건 절
    경계에서 가르니 매칭 수는 늘었지만(460->504) 군더더기가 3배(35->102)로
    늘고 유사도가 더 떨어졌다. 이미 짧은 자막은 절이 있어도 정답이 안 가른다는
    뜻 — 병합 단계에서 여러 조각이 뭉쳐 원래 길어진 자막에만 절 분할을 쓴다).
    """
    use_clause_split = force_clause_split and event.duration_ms > clause_split_min_duration_ms
    pieces = split_text(event.text, max_chars_per_cue, weights, force_sentence_split,
                        use_clause_split, min_piece_chars, target_chars)
    if len(pieces) <= 1:
        return [event]

    spans = _allocate_by_words(event.start_ms, event.end_ms, pieces, words) if words else None
    if spans is None:
        spans = _allocate(event.start_ms, event.end_ms, pieces, weights)
    spans = _snap_to_silence(spans, speech)
    return [Event(event.index, s, e, text) for (s, e), text in zip(spans, pieces)]


def resplit_all(events: list[Event], profile: dict,
                speech: list[tuple[int, int]] | None = None,
                origins: list[int] | None = None,
                words: list[tuple[int, int, str]] | None = None) -> list[Event]:
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
    max_chars_per_cue = per_line * max_lines
    timecode = profile.get("timecode") or {}
    force_sentence_split = bool(timecode.get("force_sentence_split"))
    force_clause_split = bool(timecode.get("force_clause_split"))
    min_piece_chars = float(timecode.get("min_piece_chars") or 0)
    clause_split_min_duration_ms = int(timecode.get("clause_split_min_duration_ms") or 0)

    # T14: 학습값(rules/learned/)이 있으면 자를 자리를 그 글자 수 쪽으로 당긴다.
    # 규정 상한(`max_chars_per_cue`) 자체는 안 건드린다 — 여러 합법 후보 중 어느
    # 것을 고를지만 바꾼다. 상한을 넘는 학습값은 방어적으로 자른다(원래 없어야
    # 하지만, 있으면 규정보다 학습값이 우선하는 것처럼 보이면 안 된다).
    target_chars = load_learned_chars_per_cue(
        profile.get("platform"), profile.get("language"), profile.get("kind"))
    if target_chars is not None:
        target_chars = min(target_chars, max_chars_per_cue)

    out: list[Event] = []
    for ev in events:
        pieces = resplit(ev, max_chars_per_cue, weights, speech, force_sentence_split,
                         force_clause_split, min_piece_chars, clause_split_min_duration_ms,
                         target_chars, words=words)
        out.extend(pieces)
        if origins is not None:
            origins.extend([ev.index] * len(pieces))
    for i, ev in enumerate(out, 1):
        ev.index = i
    return out
