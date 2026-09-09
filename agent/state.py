"""세션 상태 저장/복원. DECISIONS.md 3절 — 파일 기반(JSON), .work/ 관례 확장.

원본 srt는 절대 여기서 옮기지 않는다(CLAUDE.md 규칙7) — 업로드본을 세션
디렉터리로 복사해 두고, 그 복사본만 검사·교정 대상으로 삼는다.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

SESSIONS_ROOT = Path(".work/agent-session")


@dataclass
class Violation:
    rule_id: str
    article: str
    count: int
    severity: str  # "auto" | "confirm"
    locations: list[int] = field(default_factory=list)
    resolved: bool = False


@dataclass
class PendingQuestion:
    question_id: str
    version: int
    cards: list[dict]
    options: list[str]
    answered: bool = False


@dataclass
class SessionState:
    file_id: str
    status: str  # "running" | "waiting_for_user" | "done" | "error"
    platform: str
    kind: str
    language: str
    current_path: str = ""  # 이번 루프 기준 최신 작업본 — 원본(input.srt)은 안 건드림(CLAUDE.md 규칙7)
    violations: list[Violation] = field(default_factory=list)
    pending_question: PendingQuestion | None = None
    history: list[dict] = field(default_factory=list)
    result: dict | None = None
    fix_approved: bool = False
    needs_fix_approval: bool = False
    error: str | None = None
    sdk_session_id: str | None = None  # Claude Agent SDK 세션 — resume용
    outer_turns: int = 0  # run_turn() 호출 횟수(사람 왕복 포함) — 종료조건
    total_cost_usd: float = 0.0
    total_duration_ms: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    # "확인" 위반 중 이미 사람이 판단 끝낸 것 — {"rule_id:location": "승인|거부|직접수정"}.
    # run_check가 파일을 다시 훑어도 checker는 사람의 판단을 모르므로(파일 자체는
    # 안 바뀔 수 있다), 같은 자리를 다시 묻지 않으려면 이 기록이 있어야 한다.
    dispositioned: dict[str, str] = field(default_factory=dict)
    auto_fixed_count: int = 0  # run_fix가 실제로 적용한 auto 규칙 누적 건수(결과 화면 "고친 것")
    se_bookmarks_path: str | None = None  # 영상 확인 필요 위반을 SE 북마크로 내보낸 파일
    # run_check/run_fix가 성공적으로 한 번이라도 위반 목록을 얻었는지. 이게
    # 없으면 "검사 자체가 실패했다"와 "검사했는데 위반이 없다"를 못 가른다 —
    # 둘 다 violations가 빈 리스트라 실제로 이 필드 없이는 구분 불가능했다
    # (2026-09-09, amazon 미지원 발주처로 검사 자체가 실패했는데 "완료(위반
    # 0건)"으로 잘못 표시된 걸 실패사례 정리하다가 실제로 발견함).
    checked: bool = False

    def log(self, tool: str, summary: str, **extra) -> None:
        entry = {"loop": self.outer_turns, "tool": tool, "summary": summary, "at": time.time()}
        entry.update(extra)
        self.history.append(entry)


def new_file_id() -> str:
    return f"f_{uuid.uuid4().hex[:12]}"


def session_dir(file_id: str) -> Path:
    d = SESSIONS_ROOT / file_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save(state: SessionState) -> None:
    path = session_dir(state.file_id) / "state.json"
    payload = asdict(state)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load(file_id: str) -> SessionState | None:
    path = session_dir(file_id) / "state.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    violations = [Violation(**v) for v in data.get("violations", [])]
    pq_data = data.get("pending_question")
    pending_question = PendingQuestion(**pq_data) if pq_data else None
    return SessionState(
        file_id=data["file_id"],
        status=data["status"],
        platform=data["platform"],
        kind=data["kind"],
        language=data["language"],
        current_path=data.get("current_path", ""),
        violations=violations,
        pending_question=pending_question,
        history=data.get("history", []),
        result=data.get("result"),
        fix_approved=data.get("fix_approved", False),
        needs_fix_approval=data.get("needs_fix_approval", False),
        error=data.get("error"),
        sdk_session_id=data.get("sdk_session_id"),
        outer_turns=data.get("outer_turns", 0),
        total_cost_usd=data.get("total_cost_usd", 0.0),
        total_duration_ms=data.get("total_duration_ms", 0),
        total_input_tokens=data.get("total_input_tokens", 0),
        total_output_tokens=data.get("total_output_tokens", 0),
        dispositioned=data.get("dispositioned", {}),
        auto_fixed_count=data.get("auto_fixed_count", 0),
        se_bookmarks_path=data.get("se_bookmarks_path"),
        checked=data.get("checked", False),
    )
