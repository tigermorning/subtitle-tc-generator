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
