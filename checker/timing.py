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
LEAD_IN_FRAMES = (2, 3)
LEAD_OUT_FRAMES = (6, 9)

# 말소리 검출이 문장 끝의 잦아드는 소리를 일찍 자른다는 의심이 있어, 아웃점에
# 상수 보정(+400ms)을 넣어 봤다가 **뺐다**(2026-08-11). 전문가 타임코드와 대조하니
# 아웃점 중앙값이 -380ms에서 -354ms로 거의 그대로였다. 우리 자막이 빈틈없이 붙어
# 있어 늘릴 자리가 없었기 때문이다.
#
# 실제로 고친 것은 **전사 조각을 묶는 것**이었다(`regroup.py`). 자막이 줄어 사이가
# 벌어지자 아웃점이 -226ms까지 따라왔다. 증상이 아니라 원인을 고쳐야 했다.


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
                     tolerance_frames: int = 4) -> list[SpotSuggestion]:
    """말소리 구간과 견줘 인점·아웃점을 제안한다.

    **자동으로 고치지 않는다.** 말소리 검출은 음량 기준이라 배경음악이 크면 경계가
    흐려지고, 그 값으로 타임코드를 덮어쓰면 싱크가 통째로 어긋난다. 사람이 보고
    고르도록 제안만 낸다.

    `tolerance_frames`보다 적게 어긋난 것은 말하지 않는다 — 이미 규정 안이다.
    """
    if not speech:
        return []
    frame = 1000.0 / fps
    tolerance = tolerance_frames * frame
    out: list[SpotSuggestion] = []

    ordered = sorted(events, key=lambda e: e.start_ms)
    for i, ev in enumerate(ordered):
        # 다음 자막의 인점을 넘어서까지 늘리지 않는다.
        # 작업자 자료: "음성이 겹치는 경우에는 다음 화자의 인점 우선".
        next_start = ordered[i + 1].start_ms if i + 1 < len(ordered) else None

        # 이 자막과 겹치는 말소리 구간
        overlapping = [(s, e) for s, e in speech if e > ev.start_ms and s < ev.end_ms]
        if not overlapping:
            out.append(SpotSuggestion(ev.index, "start_ms", ev.start_ms, ev.start_ms,
                                      "이 구간에서 말소리를 찾지 못했습니다"
                                      " — 효과음·화면 자막이면 정상입니다"))
            continue

        voice_start = min(s for s, _ in overlapping)
        voice_end = max(e for _, e in overlapping)
        if next_start is not None:
            voice_end = min(voice_end, next_start)

        want_start = voice_start - LEAD_IN_FRAMES[1] * frame
        if abs(ev.start_ms - want_start) > tolerance:
            out.append(SpotSuggestion(
                ev.index, "start_ms", ev.start_ms, int(round(want_start)),
                f"말소리 시작 {voice_start}ms의 {LEAD_IN_FRAMES[0]}~{LEAD_IN_FRAMES[1]}프레임 앞"))

        want_end = voice_end + LEAD_OUT_FRAMES[0] * frame
        if next_start is not None:
            # 여유 프레임을 더한 뒤에도 다음 인점을 넘지 않게 한다.
            # 간격 확보는 converge()가 따로 본다.
            want_end = min(want_end, next_start)
        if abs(ev.end_ms - want_end) > tolerance:
            out.append(SpotSuggestion(
                ev.index, "end_ms", ev.end_ms, int(round(want_end)),
                f"말소리 끝 {voice_end}ms의 {LEAD_OUT_FRAMES[0]}~{LEAD_OUT_FRAMES[1]}프레임 뒤"))

    return out


# 장면 전환 규정(작업자 자료):
#   인점: 장면 전환에 딱 맞추거나 0.5초 이상 벌리기
#   아웃점: 장면 전환 -2프레임에 맞추거나 0.5초 이상 벌리기
#   쿠팡은 비적용
SHOT_CLEARANCE_MS = 500
SHOT_OUT_LEAD_FRAMES = 2


def suggest_shot_snap(events: list[Event], shots: list[int], fps: float,
                      clearance_ms: int = SHOT_CLEARANCE_MS) -> list[SpotSuggestion]:
    """장면 전환에 어설프게 걸친 타임코드를 제안한다.

    규정이 말하는 것은 **어중간하지 말라**는 것이다 — 딱 붙이거나 확실히 떨어뜨리거나.
    전환에서 `clearance_ms` 안에 있으면서 딱 맞지도 않은 자리만 지적한다.

    쿠팡처럼 장면 전환을 적용하지 않는 곳에서는 이 함수를 부르지 않는다
    (프로파일의 `shot_change.applied`가 판단한다).
    """
    if not shots:
        return []
    frame = 1000.0 / fps
    snap_tolerance = frame           # 한 프레임 안이면 이미 붙은 것으로 본다
    out: list[SpotSuggestion] = []

    for ev in events:
        for shot in shots:
            # 인점: 전환에 딱 붙이거나 0.5초 이상 벌린다
            delta = ev.start_ms - shot
            if abs(delta) <= snap_tolerance:
                break
            if abs(delta) < clearance_ms:
                out.append(SpotSuggestion(
                    ev.index, "start_ms", ev.start_ms, shot,
                    f"장면 전환 {shot}ms에 {abs(delta)}ms 차로 걸쳤습니다 —"
                    f" 딱 붙이거나 {clearance_ms}ms 이상 벌립니다"))
                break

        want_out = None
        for shot in shots:
            delta = ev.end_ms - shot
            target = int(round(shot - SHOT_OUT_LEAD_FRAMES * frame))
            if abs(ev.end_ms - target) <= snap_tolerance:
                break
            if abs(delta) < clearance_ms:
                want_out = target
                break
        if want_out is not None:
            out.append(SpotSuggestion(
                ev.index, "end_ms", ev.end_ms, want_out,
                f"장면 전환에 걸친 아웃점 — 전환 {SHOT_OUT_LEAD_FRAMES}프레임 앞에 맞추거나"
                f" {clearance_ms}ms 이상 벌립니다"))

    return out
