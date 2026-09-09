"""checker를 감싸는 public wrapper — 이 파일이 PRD_MQ4.md 도구 계획의 실제 구현이다.

`checker/cli.py::_run_one`은 private(밑줄 시작)이라 여기서는 그 내부가 쓰는
공개 함수를 직접 부른다(서브프로세스 아님, 같은 프로세스 안 라이브러리 호출):

    checker.parsers.parse      srt -> list[Event]
    checker.profile.load_profile   platform/kind/language -> 프로파일 dict
    checker.checks.run_checks      (events, profile) -> (violations, unimplemented, skipped)
    checker.fixes.apply_fixes      (events, profile) -> (fixed_events, applied_rules, unfixable_rules)
    checker.writers.write_srt      새 파일로만 쓴다(CLAUDE.md 규칙7 — 원본 불변)

에이전트(LLM)는 이 파일을 거쳐서만 자막에 닿는다 — 여기서 반환하는 것은
규칙ID·조항·건수·위치(큐 번호)뿐이고 대사 원문(Event.text)은 절대 반환하지
않는다(PRD_MQ4.md 핵심 설계 원칙).
"""
from __future__ import annotations

from pathlib import Path

from checker.bookmarks import write as _write_bookmarks
from checker.checks import run_checks
from checker.fixes import apply_fixes
from checker.parsers import parse
from checker.profile import ProfileError, load_profile
from checker.writers import write_srt

from agent.state import PendingQuestion, Violation


class CheckerToolError(Exception):
    """checker 호출 실패 — 자동 재시도하지 않고 사람에게 그대로 보여준다
    (PRD_MQ4.md "실패 처리 규칙")."""


def _load_events_and_profile(file_path: Path, platform: str, kind: str, language: str):
    events = parse(file_path)
    if not events:
        raise CheckerToolError(f"자막 이벤트를 읽지 못했습니다: {file_path.name}")
    try:
        profile = load_profile(platform, language, kind)
    except ProfileError as e:
        raise CheckerToolError(str(e)) from e
    return events, profile


def _group_by_rule(raw_violations) -> list[Violation]:
    """checker.model.Violation(개별 위반, 이벤트 단위) 여럿을 rule_id로 묶어
    PRD_MQ4.md 도구 계획의 출력 스키마({rule_id, article, count, severity,
    locations})로 바꾼다. 대사 텍스트(raw_violations의 text/message)는 여기서
    버려지고 옮기지 않는다 — 원문이 이 경계를 넘지 않는 지점이 정확히 여기다."""
    grouped: dict[str, Violation] = {}
    for v in raw_violations:
        g = grouped.get(v.rule_id)
        if g is None:
            g = Violation(
                rule_id=v.rule_id, article=v.clause, count=0,
                severity="auto" if v.auto_fixable else "confirm",
            )
            grouped[v.rule_id] = g
        # 문서 단위 검사(doc_check)는 line_no가 없다 — event_index로 폴백,
        # 그것도 없으면 큐를 특정 못 하는 전체 문서 위반이라는 뜻으로 -1을 쓴다.
        location = v.line_no if v.line_no is not None else v.event_index
        location = location if location is not None else -1
        # 같은 큐에서 같은 규칙이 여러 개별 사유로 잡히는 경우(예: 화자ID 문제가
        # 한 줄에 여러 곳)가 실제 있다 — 사람에게는 한 줄당 한 번만 확인받으면
        # 되므로 위치는 중복 없이 모은다(실사용 코퍼스로 실측, 합성 샘플에선
        # 안 나타났던 문제).
        if location not in g.locations:
            g.locations.append(location)
        g.count = len(g.locations)
    return list(grouped.values())


def check(file_path: Path, platform: str, kind: str, language: str) -> list[Violation]:
    events, profile = _load_events_and_profile(file_path, platform, kind, language)
    raw_violations, _unimplemented, _skipped = run_checks(events, profile)
    return _group_by_rule(raw_violations)


def fix(file_path: Path, output_path: Path, platform: str, kind: str, language: str) -> dict:
    events, profile = _load_events_and_profile(file_path, platform, kind, language)
    fixed_events, applied_rules, _unfixable_rules = apply_fixes(events, profile)

    write_srt(fixed_events, output_path)  # 새 파일 — file_path(직전 작업본)는 안 건드림

    post_violations, _unimplemented, _skipped = run_checks(fixed_events, profile)
    return {
        "output_path": str(output_path),
        "applied": list(applied_rules),
        "still_violating": _group_by_rule(post_violations),
    }


# 타이밍·간격류는 영상 없이 텍스트만 보고 승인/거부를 못 정한다(사용자 지적,
# 2026-09-09) — 스포팅이 화면 속 상황과 맞는지는 봐야 안다. checker/bookmarks.py의
# 기존 `timecode` 갈래 키워드와 같은 결로 고른다(그쪽은 사람이 자유 텍스트로 쓴
# 지적을 분류하고, 이쪽은 규정 조항 문구를 분류한다는 차이만 있다).
_VIDEO_NEEDED_KEYWORDS = (
    "Duration", "간격", "Spacing", "Spotting", "Timing", "프레임",
    "인점", "아웃점", "듀레이션",
)


def needs_video_review(article: str) -> bool:
    return any(kw in article for kw in _VIDEO_NEEDED_KEYWORDS)


def split_confirm_violations(confirm_violations: list[Violation]) -> tuple[list[Violation], list[Violation]]:
    """(웹에서 텍스트만으로 판단 가능한 것, 영상 확인이 필요한 것)으로 가른다."""
    web, video = [], []
    for v in confirm_violations:
        (video if needs_video_review(v.article) else web).append(v)
    return web, video


def export_bookmarks(srt_path: Path, items: list[tuple[int, str]]) -> Path:
    """`items`의 (자막 번호, 코멘트)를 SE 북마크 파일로 쓴다 — SE에서 이 srt를
    열면 그 번호에 북마크가 뜬다. `checker/bookmarks.py`가 이미 이 포맷을
    읽는 코드를 갖고 있었다(강사 첨삭 수집용) — 그 포맷 그대로 쓴다."""
    return _write_bookmarks(srt_path, items)


def build_pending_question(confirm_violations: list[Violation], question_id: str, version: int) -> PendingQuestion:
    cards = [
        {"rule_id": v.rule_id, "article": v.article, "cue_index": loc}
        for v in confirm_violations for loc in v.locations
    ]
    return PendingQuestion(
        question_id=question_id, version=version, cards=cards,
        options=["승인", "거부", "직접수정"],
    )
