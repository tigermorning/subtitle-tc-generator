"""타임코드 수렴 — 규정에 맞을 때까지 시간을 조정한다.

영상이 없어도 되는 단계다. 자막 파일만으로 최소·최대 표시 시간, 자막 간 간격,
읽기 속도를 규정 안으로 넣는다.

**규칙끼리 충돌한다.** 표시 시간을 늘리면 다음 자막과의 간격이 좁아지고, 간격을
벌리려고 앞 자막을 줄이면 최소 표시 시간을 깬다. 그래서 우선순위를 정해 놓고
수렴시킨다. 작업자 자료가 그 순서를 이미 말해 준다.

    "아웃점 규칙보다 Minimum Duration이 우선"
    "확인 순서는 '자막 사이 간격 메우기' 먼저, 그다음 '자막 사이 최소간격 설정'"

우선순위(위가 셈):
    1. 자막끼리 겹치지 않는다        — 겹치면 재생기가 어느 쪽을 버릴지 모른다
    2. 최소 표시 시간을 지킨다        — 사람이 읽을 수 없는 자막은 없느니만 못하다
    3. 자막 간 최소 간격을 지킨다     — 두 자막이 한 덩어리로 보이지 않게
    4. 최대 표시 시간을 넘지 않는다
    5. 읽기 속도를 맞춘다             — 여기까지 오면 남는 시간으로만 조정한다

**대사가 있는 자리를 넘어서까지 늘리지 않는다.** 인점은 되도록 건드리지 않고
아웃점만 뒤로 미는 것이 기본이다 — 인점은 말이 시작되는 지점이라 소리와 어긋나면
바로 티가 난다. 아웃점은 말이 끝난 뒤라 여유가 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Event
from .text import chars_per_second


@dataclass
class TimingLimits:
    min_duration_ms: int | None = None
    max_duration_ms: int | None = None
    min_gap_ms: int = 0
    max_cps: float | None = None
    char_weights: dict | None = None

    @classmethod
    def from_profile(cls, profile: dict, fps: float = 23.976,
                     children: bool = False) -> "TimingLimits":
        limits = profile.get("limits") or {}
        duration = limits.get("duration_ms") or {}
        speeds = limits.get("reading_speed_cps") or {}
        gap = limits.get("min_gap_ms") or 0
        frames = limits.get("min_gap_frames")
        if frames:
            gap = max(gap, round(frames * 1000.0 / fps))
        return cls(
            min_duration_ms=duration.get("min"),
            max_duration_ms=duration.get("max"),
            min_gap_ms=int(gap),
            max_cps=speeds.get("children" if children else "adult"),
            char_weights=limits.get("char_weights"),
        )


@dataclass
class TimingChange:
    event_index: int
    field_name: str          # start_ms | end_ms
    before: int
    after: int
    reason: str


@dataclass
class TimingResult:
    events: list[Event] = field(default_factory=list)
    changes: list[TimingChange] = field(default_factory=list)
    unresolved: list[tuple[int, str]] = field(default_factory=list)


def _set(events: list[Event], i: int, attr: str, value: int, reason: str,
         result: TimingResult) -> None:
    before = getattr(events[i], attr)
    value = int(round(value))
    if value == before:
        return
    setattr(events[i], attr, value)
    result.changes.append(TimingChange(events[i].index, attr, before, value, reason))


def converge(events: list[Event], limits: TimingLimits, rounds: int = 3) -> TimingResult:
    """규정에 맞을 때까지 반복해 조정한다.

    한 번에 끝나지 않는 이유: 앞 자막을 늘리면 뒤 자막과의 간격이 깨지고, 그것을
    고치면 또 앞이 흔들린다. 몇 바퀴 돌려 더 이상 바뀌지 않으면 멈춘다.
    끝내 못 맞춘 자리는 **고쳤다고 하지 않고** `unresolved`로 돌려준다.
    """
    work = [Event(e.index, e.start_ms, e.end_ms, e.text) for e in events]
    work.sort(key=lambda e: e.start_ms)
    result = TimingResult(events=work)

    for _ in range(rounds):
        changed_before = len(result.changes)

        for i, ev in enumerate(work):
            nxt = work[i + 1] if i + 1 < len(work) else None

            # 1. 겹침 해소 — 다음 자막 인점보다 앞서 끝나게 한다
            if nxt and ev.end_ms > nxt.start_ms:
                _set(work, i, "end_ms", nxt.start_ms - limits.min_gap_ms,
                     f"다음 자막(#{nxt.index})과 겹쳐 아웃점을 당김", result)

            # 2. 최소 표시 시간 — 아웃점을 뒤로 민다(인점은 소리와 붙어 있으므로 마지막에)
            if limits.min_duration_ms and ev.duration_ms < limits.min_duration_ms:
                want_end = ev.start_ms + limits.min_duration_ms
                room = nxt.start_ms - limits.min_gap_ms if nxt else None
                if room is None or want_end <= room:
                    _set(work, i, "end_ms", want_end, "최소 표시 시간 확보", result)
                else:
                    # 뒤로 못 밀면 앞으로 당긴다. 앞 자막 간격이 허락하는 만큼만.
                    prev = work[i - 1] if i > 0 else None
                    floor = prev.end_ms + limits.min_gap_ms if prev else 0
                    want_start = max(floor, ev.end_ms - limits.min_duration_ms)
                    if room - want_start >= limits.min_duration_ms:
                        _set(work, i, "start_ms", want_start, "최소 표시 시간 확보(인점 당김)", result)
                        _set(work, i, "end_ms", room, "최소 표시 시간 확보", result)

            # 3. 자막 간 간격
            if nxt and limits.min_gap_ms:
                gap = nxt.start_ms - ev.end_ms
                if 0 <= gap < limits.min_gap_ms:
                    want_end = nxt.start_ms - limits.min_gap_ms
                    if not limits.min_duration_ms or want_end - ev.start_ms >= limits.min_duration_ms:
                        _set(work, i, "end_ms", want_end, f"자막 간 간격 {limits.min_gap_ms}ms 확보", result)

            # 4. 최대 표시 시간
            if limits.max_duration_ms and ev.duration_ms > limits.max_duration_ms:
                _set(work, i, "end_ms", ev.start_ms + limits.max_duration_ms,
                     "최대 표시 시간 초과", result)

            # 5. 읽기 속도 — 남는 자리가 있을 때만 늘린다
            if limits.max_cps:
                cps = chars_per_second(ev.text, ev.duration_ms, limits.char_weights)
                if cps > limits.max_cps:
                    need = chars_per_second(ev.text, 1000, limits.char_weights) * 1000 / limits.max_cps
                    want_end = ev.start_ms + need
                    if limits.max_duration_ms:
                        want_end = min(want_end, ev.start_ms + limits.max_duration_ms)
                    if nxt:
                        want_end = min(want_end, nxt.start_ms - limits.min_gap_ms)
                    if want_end > ev.end_ms:
                        _set(work, i, "end_ms", want_end, "읽기 속도 확보", result)

        if len(result.changes) == changed_before:
            break

    # 끝내 못 맞춘 자리를 남긴다. 고쳤다고 말하지 않는다.
    for i, ev in enumerate(work):
        nxt = work[i + 1] if i + 1 < len(work) else None
        if limits.min_duration_ms and ev.duration_ms < limits.min_duration_ms:
            result.unresolved.append(
                (ev.index, f"최소 표시 시간 {limits.min_duration_ms}ms를 확보하지 못했습니다"
                           f"(현재 {ev.duration_ms}ms) — 앞뒤 자막과 병합을 검토하세요"))
        if nxt and ev.end_ms > nxt.start_ms:
            result.unresolved.append((ev.index, f"다음 자막(#{nxt.index})과 여전히 겹칩니다"))
        if limits.max_cps:
            cps = chars_per_second(ev.text, ev.duration_ms, limits.char_weights)
            if cps > limits.max_cps:
                result.unresolved.append(
                    (ev.index, f"읽기 속도 {cps:.1f} CPS — 시간으로는 더 못 줄입니다."
                               " 글자를 줄이거나 자막을 나누세요"))

    result.events.sort(key=lambda e: e.start_ms)
    return result


# 작업자 자료의 스포팅 기준:
#   모눈 1칸 = 0.1초 = 3프레임
#   인점: 보이스 시작 전 0.1초 이내(2~3프레임)
#   아웃점: 보이스 끝난 후 0.2~0.3초 이내(6~9프레임)
#   음성이 겹치면 다음 화자의 인점 우선
#   아웃점 규칙보다 Minimum Duration이 우선
# "한 칸 = 0.1초"는 SE 화면 실측으로 확인했다(2026-09-11, 배율 무관 초당 10칸).
# "3프레임"은 30fps 환산이다 — 24fps면 2.4, 25fps면 2.5, 60fps면 6프레임. 규정은
# **시간**이 기준이고 프레임 수는 fps에 딸린 표기다(fps별 표는
# rules/private/sources/작업자-자료/이미지-정독.md "스포팅·장면전환").
# **여유 값은 검출기에 딸린 값이다.** 작업자 기준(인점은 목소리 시작 2~3프레임 전,
# 아웃점은 끝난 뒤 6~9프레임)은 *사람이 듣는 말의 경계*를 기준으로 한 것이고,
# 검출기가 그 경계를 어디로 잡느냐는 방법마다 다르다. 같은 규정을 지키려면 검출기가
# 어긋나는 만큼을 여유로 되돌려야 한다.
#
# 정답을 아는 합성 오디오로 재 보니 VAD는 말 시작을 거의 정확히 잡았다
# (오차 +4~+11ms, 흩어짐 ±10~19ms — 한 프레임보다 작다). 음량 검출은 숨소리에
# 먼저 반응해 일찍 잡고, 말끝은 일찍 자른다.
#
# 그래서 검출기별로 값을 따로 둔다. 전문가 정답 1편과 연습 자료 2편에서 100ms 안에
# 드는 자막 수로 골랐다(2026-08-11):
#
#     인점 여유   0프레임 206  1프레임 206  2프레임 204  3프레임 186  5프레임 98
#     아웃 여유   3프레임 123  6프레임 102  9프레임  64  12프레임  57
#
# 음량 쪽 값은 그대로 둔다 — 그 값으로 잰 결과가 이미 있고, 검출기가 다르면 근거도
# 다시 세워야 한다.
#
# **이 프레임 수는 23.976fps 기준이다**(위 스윕 커밋 77dffbf가 "한 프레임 42ms"로
# 쟀다). 영상 fps가 다르면 프레임 수를 그대로 쓰지 않고 **ms로 환산해 적용한다**
# (2026-09-11) — 안 그러면 25fps에서는 같은 3프레임이 120ms, 60fps에서는 50ms가
# 돼 규정(시간 기준)에서 벗어난다. 사람이 읽는 제안 문구에는 그 영상 fps로 다시
# 환산한 프레임 수를 적는다.
LEADS_REF_FPS = 23.976
LEADS = {
    "loudness": {"in": (2, 3), "out": (6, 9), "tail": 6},
    "vad": {"in": (1, 2), "out": (3, 4), "tail": 0},
}

LEAD_IN_FRAMES = LEADS["loudness"]["in"]
LEAD_OUT_FRAMES = LEADS["loudness"]["out"]
SPEECH_TAIL_FRAMES = LEADS["loudness"]["tail"]


def leads_ms(detector: str = "loudness") -> dict:
    """LEADS의 프레임 값을 기준 fps(23.976)로 ms 환산해 돌려준다.

    영상 fps와 무관하게 같은 시간 여유를 쓰기 위한 것이다. 반환:
    ``{"in": (lo_ms, hi_ms), "out": (lo_ms, hi_ms), "tail": ms}``.
    """
    leads = LEADS.get(detector, LEADS["loudness"])
    f = 1000.0 / LEADS_REF_FPS
    return {
        "in": (leads["in"][0] * f, leads["in"][1] * f),
        "out": (leads["out"][0] * f, leads["out"][1] * f),
        "tail": leads["tail"] * f,
    }


@dataclass
class SpotSuggestion:
    event_index: int
    field_name: str
    current: int
    suggested: int
    reason: str


def apply_spotting(events: list[Event], suggestions: list) -> int:
    """제안을 타임코드에 반영한다. **생성 경로에서만 쓴다.**

    사람이 잡아 놓은 타임코드에는 쓰지 않는다(`suggest_spotting` 첫머리 참고).
    하지만 **기계가 방금 만든 타임코드**라면 이야기가 다르다 — whisper가 찍은
    경계도 어차피 추정이고, 말소리 구간과 견줘 다듬는 쪽이 낫다.

    **이웃을 넘지 않는 조정만 받는다.** 이 가드가 없어 크게 망가진 적이 있다
    (2026-08-11): 한 말소리 구간에 자막 여러 개가 걸리면 그 자막들이 **전부 같은
    경계로 스냅되어** 길이 0짜리가 무더기로 생겼다. 206개 중 85개가 길이 0이었다.

        말소리 구간 하나 [23.2s ~ 29.0s]
        그 안의 자막 여섯 개 -> 모두 23.2~29.0 -> 앞의 다섯 개가 0초로 뭉갬

    말소리 검출은 **구간**을 주지 그 안에서 화자가 몇 번 문장을 끊었는지는 모른다.
    구간의 첫 자막 인점과 마지막 자막 아웃점만 다듬고, 그 사이 경계는 whisper가
    들은 대로 둔다.
    """
    by_index = {e.index: e for e in events}
    ordered = sorted(events, key=lambda e: (e.start_ms, e.index))
    position = {e.index: i for i, e in enumerate(ordered)}
    changed = 0

    for s in suggestions:
        event = by_index.get(s.event_index)
        if event is None or s.suggested == s.current:
            continue
        i = position[event.index]
        previous = ordered[i - 1] if i > 0 else None
        following = ordered[i + 1] if i + 1 < len(ordered) else None

        if s.field_name == "start_ms":
            # 앞 자막의 아웃점보다 앞으로 가면 두 자막이 겹친다. 자기 아웃점을
            # 넘어서면 자막이 뒤집힌다.
            floor = previous.end_ms if previous else 0
            if not (floor <= s.suggested < event.end_ms):
                continue
            event.start_ms = s.suggested
        elif s.field_name == "end_ms":
            ceiling = following.start_ms if following else s.suggested + 1
            if not (event.start_ms < s.suggested <= ceiling):
                continue
            event.end_ms = s.suggested
        else:
            continue
        changed += 1
    return changed


def suggest_spotting(events: list[Event], speech: list[tuple[int, int]], fps: float,
                     tolerance_frames: int = 4,
                     detector: str = "loudness",
                     max_shift_ms: int = 2000) -> list[SpotSuggestion]:
    """말소리 구간과 견줘 인점·아웃점을 제안한다.

    **자동으로 고치지 않는다.** 말소리 검출은 음량 기준이라 배경음악이 크면 경계가
    흐려지고, 그 값으로 타임코드를 덮어쓰면 싱크가 통째로 어긋난다. 사람이 보고
    고르도록 제안만 낸다.

    `tolerance_frames`보다 적게 어긋난 것은 말하지 않는다 — 이미 규정 안이다.

    **`max_shift_ms`보다 크게 옮기는 제안은 내지 않는다.** 예능·토크쇼처럼 여러
    사람이 끊김 없이 겹쳐 말하면 VAD·음량 검출은 그 전부를 하나의 긴 말소리
    구간으로 묶어 버린다. 그러면 아웃점이 "이 자막이 담은 말이 끝나는 자리"가
    아니라 "근처 말소리 구간이 끝나는 자리"로 끌려간다 — 다음 자막이 한참 뒤에야
    시작하면 그 사이 배경 잡담·박수·노래까지 아웃점에 얹힌다(예능A
    16회 정답 대조에서 실측, 2026-08-26 — 자막 여러 개가 정확히 프로파일의
    노출 상한에 걸려서야 멈췄다. 상한이 없었다면 몇 초를 더 끌려갔을 것이다).
    이런 자리는 근거가 이 자막 하나를 가리키는 게 아니라 넓은 구간을 가리키는
    것이므로, **크게 옮기는 대신 아무 말도 하지 않는다** — 전사·재분할이 만든
    원래 값을 그대로 두고 검사(C01·S02)가 사람에게 맡긴다. 규칙 4와 같은 논리:
    여유(LEADS)는 몇 프레임 다듬는 값이지, 몇 초를 새로 정하는 값이 아니다.
    """
    if not speech:
        return []
    # 여유는 ms로 쓴다(23.976fps 실측값을 시간으로 고정) — 영상 fps가 달라도
    # 같은 시간만큼 두기 위해서다. 문구에 적는 프레임 수만 이 영상 fps로 환산한다.
    leads = leads_ms(detector)
    lead_in, lead_out, tail = leads["in"], leads["out"], leads["tail"]
    frame = 1000.0 / fps
    tolerance = tolerance_frames * frame

    def _fr(ms: float) -> str:
        return f"{ms / frame:.1f}".rstrip("0").rstrip(".")
    out: list[SpotSuggestion] = []

    ordered = sorted(events, key=lambda e: e.start_ms)
    for i, ev in enumerate(ordered):
        # 다음 자막의 인점을 넘어서까지 늘리지 않는다.
        # 작업자 자료: "음성이 겹치는 경우에는 다음 화자의 인점 우선".
        next_start = ordered[i + 1].start_ms if i + 1 < len(ordered) else None
        # **이전 자막의 아웃점보다 앞으로 당기지 않는다.** 대칭인 상한
        # (다음 인점)은 있었는데 이 하한이 없었다 — 예능처럼 끊김 없이
        # 오래 이어지는 대화에서 VAD가 수십 초짜리 말소리 구간 하나로
        # 묶으면, 그 구간에 걸친 **모든** 자막이 구간 맨 처음(수만 ms
        # 전)으로 끌려갔다(실측 2026-08-28, 예능A 15회 — #81은
        # 33,549ms, #358은 24,158ms 전으로 계산됐다. 둘 다 직전 자막과
        # 거의 붙어 있는 자리였는데 그 사실을 전혀 안 봤다). 결과적으로
        # `max_shift_ms` 상한에 걸려 조용히 버려지긴 했지만, 그 상한이
        # 진짜 필요한 작은 보정(2~3초짜리 whisper 타임스탬프 오차)까지
        # 같은 무더기로 묻어 버렸다.
        prev_end = ordered[i - 1].end_ms if i > 0 else None

        # 이 자막과 겹치는 말소리 구간
        overlapping = [(s, e) for s, e in speech if e > ev.start_ms and s < ev.end_ms]
        # **자막 밖으로 더 많이 뻗은 앞자락·뒷자락은 이웃 말의 꼬리다 — 뺀다.**
        # whisper 세그먼트가 실제 말보다 몇백 ms~1초 일찍 시작해 **직전 말의 끝
        # 구간**에 걸치면, 위 `min(s)`가 그 앞 구간의 시작을 "이 자막의 말소리
        # 시작"으로 잡고 직전 아웃점에 걸려 멈춘다 — 정작 이 자막의 진짜 온셋은
        # 그 뒤 구간에 있는데. 정답 대조(2026-09-11, 드라마B E02·E03 진짜 짝
        # 370개): VAD 온셋은 정답 인점의 +80ms 안팎(100ms 안 42~54%)에 있었는데
        # 우리 인점은 정답보다 가운데 -373/-475ms 일렀다(100ms 안 19~23%).
        # 구간이 자막 안쪽보다 바깥쪽에 더 많이 걸쳐 있으면 이웃 말로 본다 —
        # 하나뿐인 구간은 안 뺀다(자막이 그 말 위에 있는 것이 확실하다).
        def _inside(s: int, e: int) -> int:
            return max(0, min(e, ev.end_ms) - max(s, ev.start_ms))
        while (len(overlapping) > 1 and overlapping[0][0] < ev.start_ms
               and ev.start_ms - overlapping[0][0] > _inside(*overlapping[0])):
            overlapping.pop(0)
        while (len(overlapping) > 1 and overlapping[-1][1] > ev.end_ms
               and overlapping[-1][1] - ev.end_ms > _inside(*overlapping[-1])):
            overlapping.pop()
        if not overlapping:
            out.append(SpotSuggestion(ev.index, "start_ms", ev.start_ms, ev.start_ms,
                                      "이 구간에서 말소리를 찾지 못했습니다"
                                      " — 효과음·화면 자막이면 정상입니다"))
            continue

        voice_start = min(s for s, _ in overlapping)
        if prev_end is not None:
            voice_start = max(voice_start, prev_end)
        voice_end = max(e for _, e in overlapping)
        if next_start is not None:
            voice_end = min(voice_end, next_start)

        want_start = voice_start - lead_in[1]
        start_shift = abs(ev.start_ms - want_start)
        if tolerance < start_shift <= max_shift_ms:
            out.append(SpotSuggestion(
                ev.index, "start_ms", ev.start_ms, int(round(want_start)),
                f"말소리 시작 {voice_start}ms의 {_fr(lead_in[0])}~{_fr(lead_in[1])}프레임"
                f"({lead_in[0]:.0f}~{lead_in[1]:.0f}ms) 앞"))

        want_end = voice_end + tail + lead_out[0]
        if next_start is not None:
            # 여유 프레임을 더한 뒤에도 다음 인점을 넘지 않게 한다.
            # 간격 확보는 converge()가 따로 본다.
            want_end = min(want_end, next_start)
        end_shift = abs(ev.end_ms - want_end)
        if tolerance < end_shift <= max_shift_ms:
            out.append(SpotSuggestion(
                ev.index, "end_ms", ev.end_ms, int(round(want_end)),
                f"말소리 끝 {voice_end}ms의 {_fr(lead_out[0])}~{_fr(lead_out[1])}프레임"
                f"({lead_out[0]:.0f}~{lead_out[1]:.0f}ms) 뒤"))

    return out


# 근거: 넷플릭스 공식 "Timed Text Style Guide: Subtitle Timing Guidelines"
#   (https://partnerhelp.netflixstudios.com/hc/en-us/articles/360051554394,
#   확인 2026-08-28, 모든 자막에 적용 — SDH 전용 아님). **방향이 있다**:
#   - 인점: "Where dialogue starts on the shot change or **within half a
#     second past** the shot change, set the in-time to the first frame of
#     the shot change" — 대사가 전환 **뒤**(늦게) 시작할 때만 당긴다.
#   - 아웃점: "If an out-time is within half a second **of the last frame
#     before** the shot change... set the out-time to two frames before the
#     shot change" — 아웃점이 전환 **앞**(이르게)에 있을 때만 당긴다.
#   대칭이 아니다 — 대사가 전환 **전에** 시작했거나 아웃점이 전환 **뒤에**
#   있는 경우는 규정이 다루지 않는다(자연스러운 배치이므로 손댈 이유가
#   없다). 전에는 방향을 안 가리고 "가까우면 무조건 지적"했다 — 규정에
#   없는 경우까지 건드릴 뻔했다.
#   쿠팡은 비적용(작업자 자료).
#
# 호출부(cli.py·generate.py)는 프로파일의 `shot_change.applied`뿐 아니라
# `kind == "sdh"`도 함께 본다 — 실무에서 장면전환 지정은 SDH 작업에서만 하고
# 번역 자막은 TC 작업 뒤 바로 번역으로 들어간다(사용자 확인, 2026-08-31).
#
# 확인 기록(2026-08-31): SE(SubtitleEdit) "Beautify time codes" 프로필 편집
# 창의 넷플릭스 프리셋 값도 이 두 상수와 정확히 같다 — SE 소스
# (`src/libse/Settings/BeautifyTimeCodesSettings.cs`, `Preset.Netflix`)에
# `OutCuesGap = 2`(=`SHOT_OUT_LEAD_FRAMES`), `InCuesGap = 0`(인점은 전환에
# 바로 붙인다), 초록 영역(soft zone) `12`프레임 — 24fps에서 정확히 0.5초라
# `SHOT_CLEARANCE_MS = 500`과 같은 값이다(다른 fps에서도 SE는 이 정수를
# fps에 맞춰 바꾸지 않는다 — 상수 그대로다). 같은 프리셋의 빨간 영역(hard
# zone, `InCuesLeftRedZone = 7` 등)은 두 소프트/하드 임계값을 나눠 세부
# 우선순위(연결된 자막·체이닝)를 다루는 SE만의 UI 개념이고, 넷플릭스 공식
# 문서(위 인용)엔 그런 2단계 구분이 없다 — 그래서 여기 상수로 옮기지 않았다.
# `rules/private/sources/작업자-자료/이미지-정독.md`의 "SE '프로필 편집' 프레임 표"
# 절에 fps별 환산표와 함께 이 결론을 적어 뒀다.
SHOT_CLEARANCE_MS = 500
SHOT_OUT_LEAD_FRAMES = 2


def suggest_shot_snap(events: list[Event], shots: list[int], fps: float,
                      clearance_ms: int = SHOT_CLEARANCE_MS) -> list[SpotSuggestion]:
    """장면 전환에 어설프게 걸친 타임코드를 제안한다. 방향이 있다(위 주석).

    쿠팡처럼 장면 전환을 적용하지 않는 곳, 번역 자막(SDH가 아닌 kind)에서는
    이 함수를 부르지 않는다 — 호출부가 `shot_change.applied`와
    `kind == "sdh"`를 함께 판단한다.
    """
    if not shots:
        return []
    frame = 1000.0 / fps
    snap_tolerance = frame           # 한 프레임 안이면 이미 붙은 것으로 본다
    out: list[SpotSuggestion] = []

    for ev in events:
        for shot in shots:
            # 인점: 대사가 전환 뒤 0.5초 이내에 시작할 때만 전환 첫 프레임으로 당긴다.
            delta = ev.start_ms - shot   # 양수만 본다 — 전환보다 늦게 시작한 경우
            if 0 <= delta <= snap_tolerance:
                break
            if 0 < delta < clearance_ms:
                out.append(SpotSuggestion(
                    ev.index, "start_ms", ev.start_ms, shot,
                    f"장면 전환 {shot}ms 뒤 {delta}ms 만에 시작합니다 —"
                    f" 전환 첫 프레임으로 당깁니다"))
                break

        for shot in shots:
            # 아웃점: 전환 앞 0.5초 이내에 끝날 때만 전환 2프레임 전으로 당긴다.
            delta = shot - ev.end_ms   # 양수만 본다 — 전환보다 일찍 끝난 경우
            target = int(round(shot - SHOT_OUT_LEAD_FRAMES * frame))
            if abs(ev.end_ms - target) <= snap_tolerance:
                break
            if 0 < delta < clearance_ms:
                out.append(SpotSuggestion(
                    ev.index, "end_ms", ev.end_ms, target,
                    f"장면 전환 {shot}ms 앞 {delta}ms 만에 끝납니다 —"
                    f" 전환 {SHOT_OUT_LEAD_FRAMES}프레임 전으로 당깁니다"))
                break

    return out
