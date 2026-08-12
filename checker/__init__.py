"""플랫폼 규정 준수 검사기.

코어는 순수 함수다: 이벤트 배열 + 프로파일 -> 위반 목록. 파일 IO와 CLI는 바깥에 있다.
"""

from __future__ import annotations

from .model import Event, Report, Violation
from .profile import load_profile, available_profiles, ProfileError
from .checks import run_checks

__all__ = [
    "Event",
    "Report",
    "Violation",
    "load_profile",
    "available_profiles",
    "ProfileError",
    "check_events",
]


def check_events(events: list[dict], profile: dict, children: bool = False,
                 fps: float | None = None,
                 busy_spans: list[tuple[int, int]] | None = None,
                 job_rules=None, cast: dict[str, str] | None = None) -> dict:
    """JSON in / JSON out. 편집기가 어떤 언어로 만들어지든 이 계약만 지키면 된다."""
    parsed = [Event.from_dict(e) for e in events]
    violations, unimplemented, skipped = run_checks(
        parsed, profile, children=children, fps=fps, busy_spans=busy_spans,
        job_rules=job_rules, cast=cast)
    report = Report(
        profile=f"{profile.get('platform')}/{profile.get('language')}",
        kind=profile.get("kind", ""),
        language=profile.get("language", ""),
        violations=violations,
        unimplemented_checks=unimplemented,
    )
    out = report.to_dict()
    src = profile.get("source") or {}
    label = src.get("section") or src.get("client") or ""
    if src.get("revision"):
        label = f"{label} ({src['revision']} 개정)" if label else f"{src['revision']} 개정"
    if src.get("client") and src.get("section"):
        label = f"{label} / 발주처: {src['client']}"
    out["profile_source"] = label
    # **자료가 없어 못 돈 검사.** 미구현과 다르지만 숨기면 똑같이 "통과"로 보인다.
    if skipped:
        out["skipped_checks"] = skipped
    return out
