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
               max_gap_ms: int = MAX_GAP_MS) -> list[Event]:
    """이어지는 자막을 합친다. 번호는 다시 매긴다.

    합치는 조건은 둘뿐이다.

        사이가 `max_gap_ms` 이내로 붙어 있다   (말이 이어지고 있다)
        합쳐도 `max_duration_ms`를 넘지 않는다 (한 화면에 오래 머물지 않는다)

    말이 끊긴 자리(간격이 넓은 자리)는 합치지 않는다. 거기가 사람도 끊는 자리다.
    """
    if max_duration_ms <= 0:
        return events

    out: list[Event] = []
    for event in events:
        if out:
            previous = out[-1]
            gap = event.start_ms - previous.end_ms
            if 0 <= gap <= max_gap_ms and (event.end_ms - previous.start_ms) <= max_duration_ms:
                previous.end_ms = event.end_ms
                previous.text = f"{previous.text} {event.text}".strip()
                continue
        out.append(Event(len(out) + 1, event.start_ms, event.end_ms, event.text))
    return out


def limits_from_profile(profile: dict) -> tuple[int, int]:
    """프로파일이 값을 정했으면 그것을 쓴다. 발주처마다 호흡이 다르다."""
    timecode = (profile or {}).get("timecode") or {}
    return (int(timecode.get("merge_max_ms") or MAX_DURATION_MS),
            int(timecode.get("merge_max_gap_ms") or MAX_GAP_MS))
