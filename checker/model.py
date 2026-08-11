"""검사기의 자료형. 코어는 JSON in / JSON out 순수 함수다.

파일 IO·CLI·자막 파싱은 이 바깥에 둔다. 나중에 편집기를 다른 언어로 만들더라도
`check_events()`의 계약(이벤트 배열 + 프로파일 -> 위반 목록)은 그대로 옮겨진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Event:
    """자막 한 덩어리. 타임코드는 밀리초 정수로만 다룬다(프레임레이트 의존을 피한다)."""

    index: int
    start_ms: int
    end_ms: int
    text: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def lines(self) -> list[str]:
        return self.text.replace("\r\n", "\n").split("\n")

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            index=int(d["index"]),
            start_ms=int(d["start_ms"]),
            end_ms=int(d["end_ms"]),
            text=str(d["text"]),
        )


@dataclass
class Violation:
    """위반 하나. `clause`가 비면 안 된다 — 조항을 대지 못하는 지적은 이 도구의 존재 이유에 어긋난다."""

    rule_id: str
    clause: str
    event_index: int
    message: str
    detail: str = ""
    auto_fixable: bool = False
    line_no: int | None = None
    # 근거의 출처. 사용자가 신뢰도를 스스로 판단할 수 있어야 한다.
    #   rule      — 플랫폼 규정 프로파일
    #   corrector — 한국어 교정기(사전·어문 규범)
    source: str = "rule"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    profile: str
    kind: str
    language: str
    violations: list[Violation] = field(default_factory=list)
    unimplemented_checks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "kind": self.kind,
            "language": self.language,
            "violations": [v.to_dict() for v in self.violations],
            # 프로파일에 있지만 검사기가 아직 구현하지 않은 규칙. 숨기지 않는다 —
            # 조용히 빠지면 "전부 통과"가 거짓말이 된다.
            "unimplemented_checks": self.unimplemented_checks,
        }
