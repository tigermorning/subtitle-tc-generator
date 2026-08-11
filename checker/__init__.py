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


def check_events(events: list[dict], profile: dict, children: bool = False) -> dict:
    """JSON in / JSON out. 편집기가 어떤 언어로 만들어지든 이 계약만 지키면 된다."""
    parsed = [Event.from_dict(e) for e in events]
    violations, unimplemented = run_checks(parsed, profile, children=children)
    report = Report(
        profile=f"{profile.get('platform')}/{profile.get('language')}",
        kind=profile.get("kind", ""),
        language=profile.get("language", ""),
        violations=violations,
        unimplemented_checks=unimplemented,
    )
    return report.to_dict()
