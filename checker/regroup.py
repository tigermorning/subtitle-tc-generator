"""전사 조각을 자막 단위로 다시 묶는다.

whisper는 **말이 잠깐 멎을 때마다** 끊는다. 사람이 잡는 자막은 그렇지 않다 —
한 호흡을 한 자막에 담고, 짧은 조각은 앞뒤와 합친다.

전문가가 잡은 타임코드와 대조해 그 차이를 쟀다(2026-08-11, 6분 30초 영어 영상):

    whisper 조각 161개, 길이 중앙값 2000ms, 조각 사이 간격 중앙값 0ms
    전문가  자막 123개, 길이 중앙값 2671ms, 자막 사이 간격 중앙값 84ms

    전문가 자막 하나에 whisper 조각이 몇 개 걸치나
        1개 …  19개
        2개 …  79개   <- 대부분 둘을 합친 것이다
        3개 …  22개

그래서 **합치는 단계**를 둔다. 상한을 바꿔 가며 정답과 대조해 값을 골랐다.

    상한 없음  자막 162개  길이 중앙값 2180ms
    3500ms     자막 144개  길이 중앙값 2500ms
    **4000ms** 자막 136개  길이 중앙값 2680ms   <- 정답 2671ms와 거의 같다
    5000ms     자막 127개  길이 중앙값 2846ms   (짝을 못 찾는 자막이 늘어난다)

**글자 수는 보지 않는다.** 원어 자막의 글자 수는 납품물과 무관하다 — 16자 규정은
한국어 기준이고, 한국어 글자 수는 번역이 끝난 뒤 `resplit`이 맞춘다. 처음에는 여기서
글자 수를 보다가 합치기가 거의 일어나지 않았다(영어 두 조각이면 이미 32자를 넘는다).

**자료 하나로 정한 값이다.** 정답 파일이 더 쌓이면 다시 재야 한다.
"""

from __future__ import annotations

import re

from .model import Event

MAX_DURATION_MS = 4000
MAX_GAP_MS = 250


def merge_cues(events: list[Event], max_duration_ms: int = MAX_DURATION_MS,
               max_gap_ms: int = MAX_GAP_MS,
               speaker_turns: list[tuple[int, int, str]] | None = None) -> list[Event]:
    """이어지는 자막을 합친다. 번호는 다시 매긴다.

    합치는 조건은 셋이다.

        사이가 `max_gap_ms` 이내로 붙어 있다   (말이 이어지고 있다)
        합쳐도 `max_duration_ms`를 넘지 않는다 (한 화면에 오래 머물지 않는다)
        **화자가 바뀌지 않았다**(`speaker_turns`를 줬을 때만 본다)

    말이 끊긴 자리(간격이 넓은 자리)는 합치지 않는다. 거기가 사람도 끊는 자리다.

    **화자 판단은 `diarize.py`가 준 것이 있을 때만 본다.** 없으면(기본값)
    예전처럼 간격·길이만 본다 — 화자 분리는 별도 모델(`--diarize`)이 필요한
    선택 기능이라 없어도 기존 동작이 그대로다. 화자표를 모르는 쪽(짧은 침묵
    사이 등)은 "같은 화자"로 보고 합친다 — 모르는 것을 억지로 갈라놓지 않는다
    (규칙 4와 같은 정신 — 확실하지 않으면 손해가 적은 쪽으로 둔다. 잘못 합쳐도
    사람이 나중에 갈라놓을 수 있지만, 잘못 가르면 문장이 부서진 채로 남는다).
    """
    if max_duration_ms <= 0:
        return events

    from .diarize import speaker_at

    out: list[Event] = []
    # **원래 조각의 중간 지점끼리 비교한다.** `previous.end_ms`(누적된 자막의
    # 끝)와 `event.start_ms`(다음 조각의 시작)로 비교했더니, 간격 0인 병합
    # (whisper 조각이 딱 붙어 있는 흔한 경우)에서 두 값이 **같은 시각**이 돼
    # 화자 비교가 항상 "안 바뀜"으로 나왔다(실측 2026-08-27: 예능A 15회
    # "미스터 조" 구간에서 화자 분리를 켜도 병합이 1103개로 똑같았다 — 이
    # 버그 때문에 화자 비교가 한 번도 실제로 작동하지 않았다). `previous`는
    # 이미 여러 조각이 합쳐진 자막이라 그 중간 지점도 못 믿는다 — 그래서
    # "마지막으로 본 원래 조각"(`last_raw`)을 따로 들고 다니며 그 조각 자체의
    # 중간 지점과 새 조각의 중간 지점을 비교한다. 둘 다 각 조각 안에 있는
    # 시각이라 겹치는 경계 문제가 없다.
    last_raw: Event | None = None
    for event in events:
        if out and last_raw is not None:
            previous = out[-1]
            gap = event.start_ms - previous.end_ms
            speaker_changed = False
            if speaker_turns:
                prev_mid = (last_raw.start_ms + last_raw.end_ms) // 2
                cur_mid = (event.start_ms + event.end_ms) // 2
                prev_speaker = speaker_at(prev_mid, speaker_turns)
                cur_speaker = speaker_at(cur_mid, speaker_turns)
                speaker_changed = bool(prev_speaker and cur_speaker
                                       and prev_speaker != cur_speaker)
            if (not speaker_changed and 0 <= gap <= max_gap_ms
                    and (event.end_ms - previous.start_ms) <= max_duration_ms):
                previous.end_ms = event.end_ms
                previous.text = f"{previous.text} {event.text}".strip()
                last_raw = event
                continue
        out.append(Event(len(out) + 1, event.start_ms, event.end_ms, event.text))
        last_raw = event
    return out


def limits_from_profile(profile: dict) -> tuple[int, int]:
    """프로파일이 값을 정했으면 그것을 쓴다. 발주처마다 호흡이 다르다."""
    timecode = (profile or {}).get("timecode") or {}
    return (int(timecode.get("merge_max_ms") or MAX_DURATION_MS),
            int(timecode.get("merge_max_gap_ms") or MAX_GAP_MS))


INTERNAL_DUPLICATE_MIN_SIMILARITY = 0.85


def collapse_internal_duplicates(events: list[Event],
                                 min_similarity: float = INTERNAL_DUPLICATE_MIN_SIMILARITY) -> list[Event]:
    """자막 한 덩어리 **안**에 같은 말이 겹쳐 들어온 자리를 하나로 줄인다.

    **`compress_reaction_runs`와 다른 문제다.** 그건 서로 다른 이벤트(자막
    후보) 여러 개가 반복될 때를 다룬다. 이건 whisper가 애초에 **이벤트 하나의
    텍스트 안**에 같은 말을 두 번(또는 그 이상) 담아서 내놓는 경우다 —
    2026-08-30, 예능A 15·16회 원시 세그먼트에서 19곳 발견: "안녕하세요.
    안녕하세요.", "감사합니다. 감사합니다.", "-미스터 조는 넌 아니야? -미스터
    조는 넌 아니야?" 등. 화자 둘이 거의 동시에 같은 말을 했거나 한 화자가
    강조로 반복한 것으로 보인다(다수가 "-"로 시작해 whisper 자신도 이걸 두
    발화로 인식한 흔적이 있다). 시간대는 하나인데 텍스트만 두 번 들어와 있어,
    그대로 두면 `resplit.py`가 문장부호 기준으로 잘라 정답에 없는 자막을
    하나 더 만들어낸다(예: "이건 어때? 이건 어때?" -> 자막 2개).

    **텍스트는 지어내지 않는다(규칙 4)** — 겹친 것 중 한 벌만 남기지, 새로
    쓰지 않는다. 시간대(`start_ms`~`end_ms`)도 원래 그대로 둔다 — 어느 절반이
    "진짜" 시간인지 알 근거가 없어서 손대지 않는다.

    **재귀적으로 적용한다.** "올라! 올라! 올라! 올라! 올라! 올라!"처럼 세 번
    이상 겹치면 한 번에 반으로만 줄고 끝난다(2026-08-30 실측) — 더 줄일 자리가
    없을 때까지 반복한다.
    """
    from .align import similarity

    def _collapse_once(text: str) -> tuple[str, bool]:
        best = None
        for m in re.finditer(r"\s+", text):
            pos = m.start()
            left, right = text[:pos].strip(), text[pos:].strip()
            if not left or not right:
                continue
            sim = similarity(left, right)
            if sim >= min_similarity:
                balance = 1 - abs(len(left) - len(right)) / max(len(text), 1)
                score = sim + balance
                if best is None or score > best[0]:
                    best = (score, left)
        return (best[1], True) if best else (text, False)

    out = []
    for e in events:
        text = e.text.strip()
        changed = True
        while changed:
            text, changed = _collapse_once(text)
        out.append(Event(len(out) + 1, e.start_ms, e.end_ms, text))
    return out


REACTION_MAX_GAP_MS = 1500
REACTION_MAX_CHARS = 20
REACTION_MIN_SIMILARITY = 0.5


def compress_reaction_runs(events: list[Event], max_gap_ms: int = REACTION_MAX_GAP_MS,
                           max_chars: float = REACTION_MAX_CHARS,
                           min_similarity: float = REACTION_MIN_SIMILARITY,
                           weights: dict | None = None) -> list[Event]:
    """짧은 반응이 연달아 겹치면 하나로 압축한다.

    **왜 있나.** `merge_cues()`는 "한 호흡"을 합친다 — 말이 끊기지 않고 이어지는
    자리다. 이건 다른 문제다: 서로 짧게 떨어진(간격이 있는) **여러 개의 별도
    반응**(감탄사·짧은 대꾸)이 정답 SDH에서는 화면 하나에 압축돼 나온다
    (2026-08-30, 예능A 16회 실측 — 우리는 "아…"를 네 자막으로 나눠 냈는데
    정답은 한 자막으로 압축했다. 15·16회·SDH·번역 네 파일 전부에서 이 패턴이
    9~16묶음씩 나옴). `merge_cues()`의 `max_gap_ms`(보통 100~500ms)로는 이 간격을
    못 잡는다 — 반응 사이 간격이 그보다 넓을 때가 많아서 일부러 더 너그러운
    상한(`max_gap_ms` 여기서는 기본 1500ms)을 따로 둔다.

    **`max_chars` 20자(2026-08-30 15/16회 2차 진단으로 조정, 원래 15자)**:
    16회에서 "이 노래는 너무 좋지 않나요?"(16자)가 정확히 2000ms씩 4번, 간격
    0ms로 완전히 똑같이 반복된 자리를 발견했다 — 사람 말이 아니라 whisper가
    노래 구간을 반복 오인식한 환각으로 보인다(예능A 15·16회에서 하나뿐이라
    아직 다른 작품 확인은 없음). 15자 상한에 걸려 안 잡혔던 사례라 20자로
    넓혔다 — 글자 수가 길수록 우연히 비슷할 확률은 오히려 낮아지므로(짧은
    "네"·"아"가 우연히 겹칠 확률이 긴 문장보다 높다) 상한을 넓히는 쪽이
    안전하다.

    **텍스트는 지어내지 않는다(규칙 4).** 진짜 정답(예: "- [서연] 아, 맞다, 맞다 /
    - [우재] 그렇지 않아? 아")은 SDH 편집자가 내용을 다시 쓴 것으로 보이는데,
    우리는 그 창작적 선택을 흉내 낼 근거가 없다. 그래서 **시간만 정답 방식대로
    압축하고, 텍스트는 실제로 들은 것 중에서만 고른다** — 서로 다른(비슷하지 않은)
    문구를 순서대로 최대 2개까지 남기고, 나머지 중복은 버린다. 화자가 진짜
    다른지는 모르므로(diarize 없이는 알 수 없다) 이름은 안 붙이고 `-`만 쓴다.
    2개 이상 서로 다른 문구가 있으면 두 줄(`-A\n-B`)로, 사실상 전부 같은 말이면
    한 줄로 남긴다.
    """
    from .align import similarity
    from .text import count_chars

    out: list[Event] = []
    i = 0
    n = len(events)
    while i < n:
        if count_chars(events[i].text, weights) > max_chars:
            out.append(events[i])
            i += 1
            continue

        run = [events[i]]
        j = i + 1
        while j < n:
            candidate = events[j]
            gap = candidate.start_ms - run[-1].end_ms
            if (0 <= gap <= max_gap_ms
                    and count_chars(candidate.text, weights) <= max_chars
                    and similarity(run[0].text, candidate.text) >= min_similarity):
                run.append(candidate)
                j += 1
                continue
            break

        if len(run) >= 2:
            distinct: list[str] = []
            for e in run:
                if not distinct or similarity(distinct[-1], e.text) < min_similarity:
                    distinct.append(e.text)
                if len(distinct) >= 2:
                    break
            text = distinct[0] if len(distinct) == 1 else f"-{distinct[0]}\n-{distinct[1]}"
            out.append(Event(len(out) + 1, run[0].start_ms, run[-1].end_ms, text))
        else:
            out.append(Event(len(out) + 1, run[0].start_ms, run[0].end_ms, run[0].text))
        i = j if j > i else i + 1

    return out
