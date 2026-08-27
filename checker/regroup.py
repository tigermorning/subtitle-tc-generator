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
