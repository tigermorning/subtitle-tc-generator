"""Claude Agent SDK로 실제 계획→도구호출→관찰→다음행동 루프를 돌린다.

PRD_MQ4.md "도구 vs AI 판단 vs 사람 결정" 표의 AI 판단 칸(②자동/확인 분기,
④확인카드 그룹핑, ⑥완료판정)이 여기서 진짜 LLM 호출로 이뤄진다. 대사를
읽고 고치는 일은 여전히 agent/tools.py(결정론적 checker 호출)만 한다 —
이 파일의 도구 핸들러는 그 결과를 규칙ID·건수로만 모델에 돌려준다.

핵심 메커니즘 — can_use_tool로 사람 개입 지점 만들기:
    run_fix    fix_approved가 아직 False면 거부(interrupt=True) — 이번 턴은
               거기서 멈추고 상태만 "승인 대기"로 바뀐다.
    ask_human  호출 자체를 항상 거부(interrupt=True)한다 — 실제로 실행되는
               도구가 아니라, 모델이 "여기서 사람에게 물어야 한다"고 판단했다는
               신호로만 쓴다. 거부되는 순간 tool_input(카드로 무엇을 물을지)을
               그대로 확인 카드로 저장한다.
run_check는 안전(읽기전용)해서 allowed_tools로 바로 자동승인한다 —
can_use_tool을 거치는 두 도구와 위험도가 다르다는 걸 코드로도 갈라놓는다.
"""
from __future__ import annotations

import json
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from agent import tools as checker_tools
from agent.state import PendingQuestion, SessionState, Violation, session_dir

REPO_ROOT = Path(__file__).resolve().parent.parent

MAX_OUTER_TURNS = 8  # PRD_MQ4.md 종료조건 — 사람 왕복 포함 이 이상 넘기면 강제로 사람에게 넘긴다
MAX_TURNS_PER_CALL = 10  # 한 번의 query() 안에서 모델이 도구를 부를 수 있는 최대 횟수
MAX_BUDGET_USD_PER_CALL = 0.50  # PRD_MQ4.md "종료조건 — 비용 한도"


def _build_done_result(state: SessionState) -> dict:
    """완료 화면·리포트가 보여줄 값. 관찰가능성 요구사항(MQ4 조건4 — 소요시간·
    토큰·비용)을 여기 한곳에 모은다. "고쳤다"(fixed)와 "SE로 넘겼다"(se_review)를
    안 섞는다 — SE 이관은 사람이 아직 안 본 것이라 "완료"의 의미가 다르다."""
    se_count = sum(1 for v in state.dispositioned.values() if v == "SE로 이관")
    web_count = len(state.dispositioned) - se_count
    return {
        "fixed": state.auto_fixed_count + web_count,
        "se_review": se_count,
        "se_bookmarks_path": state.se_bookmarks_path,
        "remaining": 0,
        "loop_count": state.outer_turns,
        "cost_usd": round(state.total_cost_usd, 4),
        "duration_ms": state.total_duration_ms,
        "input_tokens": state.total_input_tokens,
        "output_tokens": state.total_output_tokens,
    }

SYSTEM_PROMPT = """너는 자막 QC 승인 에이전트다. subtitle-tc-generator의 checker 규정검사
엔진을 도구로 써서, 발주처 규정 위반이 0건이 되거나 확인만 남을 때까지 검사와
자동교정을 반복한다.

절대 규칙: 너는 자막 대사 원문을 볼 수도 없고 요청해서도 안 된다. 도구는
규칙ID·조항·건수·큐 번호 같은 구조화된 신호만 돌려준다 — 그게 전부고, 그걸로
충분해야 한다.

절차:
1. run_fix의 결과(아직 안 불렀다면 먼저 run_check)를 보고 "auto"(자동) 위반이
   남아 있으면 run_fix를 호출해라. 사람 승인이 아직 없으면 도구가 거부되고
   이유가 돌아온다 — 그러면 이번 턴은 거기서 끝내라, 다시 시도하지 마라.
2. run_fix가 끝나면 그 결과(still_violating)로 다음을 판단해라 — 다시 run_check를
   부를 필요는 없다, run_fix가 이미 최신 상태를 알려준다.
3. "confirm"(확인) 위반만 남았으면 ask_human을 불러 사람에게 물어라. reason에는
   왜 지금 물어야 하는지 한 문장으로 적어라. 이 도구는 항상 실행이 거부되고
   이번 턴이 거기서 끝난다 — 정상이다, 사람 답변은 다음 턴에 온다.
4. auto도 confirm도 안 남았으면 "완료"라고 한 문장으로만 답하고 끝내라.
5. 한 턴 안에서 스스로 다음 행동을 정하고 필요한 도구를 순서대로 불러라 —
   사람이 다음에 뭘 하라고 시키지 않는다."""


def _sig(rule_id: str, location) -> str:
    return f"{rule_id}:{location}"


def _refresh_violations(state: SessionState, grouped: list[Violation]) -> list[Violation]:
    """checker가 돌려준 최신 위반 목록에서, 사람이 이미 판단 끝낸 confirm
    항목을 걷어낸다. auto 위반은 파일이 실제로 안 고쳐졌으면 그대로 남는다
    (사람 판단으로 지울 수 있는 게 아니라서 dispositioned 대상이 아니다)."""
    outstanding: list[Violation] = []
    for v in grouped:
        if v.severity == "confirm":
            remaining_locations = [loc for loc in v.locations if _sig(v.rule_id, loc) not in state.dispositioned]
            if not remaining_locations:
                continue
            v = Violation(rule_id=v.rule_id, article=v.article, count=len(remaining_locations),
                          severity=v.severity, locations=remaining_locations)
        outstanding.append(v)
    state.violations = outstanding
    return outstanding


def _build_tools(state: SessionState):
    @tool("run_check", "checker로 현재 srt의 발주처 규정 위반을 검사한다. "
          "대사 원문은 절대 안 돌려주고 규칙ID·조항·건수·자동/확인 구분·큐번호만 돌려준다.", {})
    async def run_check(_args):
        raw = checker_tools.check(Path(state.current_path), state.platform, state.kind, state.language)
        state.checked = True  # 여기 도달했다는 건 검사가 실제로 성공했다는 뜻
        outstanding = _refresh_violations(state, raw)
        state.log("run_check", f"위반 {len(outstanding)}종 남음(이미 판단된 {len(state.dispositioned)}건 제외)")
        payload = [{"rule_id": v.rule_id, "article": v.article, "count": v.count,
                     "severity": v.severity, "locations": v.locations} for v in outstanding]
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}

    @tool("run_fix", "자동교정 가능(auto)한 위반을 실제로 적용해 새 srt 파일을 쓴다. "
          "원본은 절대 안 건드린다. 최초 1회는 사람 승인이 필요한 위험한 도구다.", {})
    async def run_fix(_args):
        out = session_dir(state.file_id) / f"{state.outer_turns:02d}-fixed.srt"
        result = checker_tools.fix(Path(state.current_path), out, state.platform, state.kind, state.language)
        state.checked = True  # fix는 내부에서 재검사까지 하므로 이것도 검사 성공이다
        state.current_path = result["output_path"]
        state.auto_fixed_count += len(result["applied"])
        outstanding = _refresh_violations(state, result["still_violating"])
        state.log("run_fix", f"{len(result['applied'])}건 자동교정 적용 -> {out.name}, {len(outstanding)}종 남음")
        payload = {
            "applied": result["applied"],
            "still_violating": [{"rule_id": v.rule_id, "article": v.article, "count": v.count,
                                   "severity": v.severity, "locations": v.locations} for v in outstanding],
        }
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}

    @tool("ask_human", "확인이 필요한 위반을 사람에게 보여주고 승인/거부/직접수정 답을 받는다. "
          "부르는 즉시 이번 턴이 끝난다 — 사람 답변은 다음 턴에 온다.",
          {"reason": str})
    async def ask_human(_args):
        # can_use_tool이 항상 먼저 가로채 거부하므로 이 핸들러 자체는 실행되지 않는다.
        return {"content": [{"type": "text", "text": "(도달하면 안 됨)"}]}

    return [run_check, run_fix, ask_human]


def _make_can_use_tool(state: SessionState, flags: dict):
    async def can_use_tool(tool_name, tool_input, _context):
        if tool_name == "mcp__subtitle_qc__run_fix" and not state.fix_approved:
            state.needs_fix_approval = True
            flags["interrupted"] = True
            state.log("permission", "run_fix — 자동교정 적용 전 사람 승인 필요, 거부함")
            return PermissionResultDeny(
                message="자동 교정 적용 전 사람 승인이 필요합니다. 이번 턴은 여기서 멈춥니다.",
                interrupt=True,
            )
        if tool_name == "mcp__subtitle_qc__ask_human":
            reason = tool_input.get("reason", "")
            confirm_pending = [v for v in state.violations if v.severity == "confirm"]
            web_violations, video_violations = checker_tools.split_confirm_violations(confirm_pending)

            if video_violations:
                # 타이밍·간격류는 영상 없이 텍스트만으로 승인/거부를 못 정한다
                # (사용자 지적, 2026-09-09) — 웹 카드에 안 올리고 SE 북마크로
                # 내보낸다. dispositioned에 넣어야 다음 run_check에서 안 다시 잡힌다.
                items = []
                for v in video_violations:
                    for loc in v.locations:
                        items.append((loc, f"[{v.rule_id}] {v.article} — 에이전트 확인 필요(영상 확인 대상)"))
                        state.dispositioned[_sig(v.rule_id, loc)] = "SE로 이관"
                bookmarks_path = checker_tools.export_bookmarks(Path(state.current_path), items)
                state.se_bookmarks_path = str(bookmarks_path)
                state.log("bookmarks", f"영상 확인 필요 {len(items)}건 -> {bookmarks_path.name}(SE 북마크)")
                state.violations = _refresh_violations(state, state.violations)
                web_violations = [v for v in state.violations if v.severity == "confirm"]

            if web_violations:
                state.pending_question = checker_tools.build_pending_question(
                    web_violations, question_id=f"q_{state.outer_turns}", version=1,
                )
            elif not confirm_pending:
                # 확인 위반이 애초에 하나도 없는데 모델이 사람을 불렀다 — 대개
                # run_check/run_fix 자체가 실패한 상황(예: 프로파일 없는 발주처).
                # 카드 목록이 비면 화면에 아무것도 안 보이므로, reason을 그대로
                # 담은 일반 질문 카드를 만들어 최소한 "왜 멈췄는지"는 보이게 한다.
                state.pending_question = PendingQuestion(
                    question_id=f"q_{state.outer_turns}", version=1,
                    cards=[{"rule_id": "-", "article": reason or "에이전트가 사람의 판단을 요청했습니다.", "cue_index": -1}],
                    options=["확인함"],
                )
            # else: confirm_pending은 있었지만 전부 영상 확인 대상으로 빠졌다 —
            # 웹에서 물을 게 더 없다. pending_question은 None으로 남기고, 아래
            # 상태 판정에서 남은 위반 0건이면 done으로 처리된다.

            if state.pending_question:
                state.log("ask_human", reason or f"확인 카드 {len(state.pending_question.cards)}건 제시")
            else:
                state.log("ask_human", reason or f"{len(video_violations)}건 SE로 이관, 웹에서 물을 것 없음")
            flags["interrupted"] = True
            return PermissionResultDeny(
                message="사용자에게 전달했습니다. 답변이 올 때까지 기다리세요.",
                interrupt=True,
            )
        return PermissionResultAllow()

    return can_use_tool


async def run_turn(state: SessionState, prompt: str) -> None:
    """한 번의 query() 호출(=한 턴)을 실행하고 state를 그 자리에서 갱신한다.

    호출 전에 반드시 needs_fix_approval/pending_question을 정리해 두는 건
    호출부(agent/api.py) 책임이다 — 여기는 SDK 한 턴을 도는 것만 한다.
    """
    if state.outer_turns >= MAX_OUTER_TURNS:
        state.status = "waiting_for_user"
        state.needs_fix_approval = False
        if state.pending_question is None:
            confirm_pending = [v for v in state.violations if v.severity == "confirm"]
            state.pending_question = checker_tools.build_pending_question(
                confirm_pending, question_id=f"q_maxturn_{state.outer_turns}", version=1,
            )
        state.log("loop", f"{MAX_OUTER_TURNS}회 왕복에도 안 끝나 강제로 사람에게 넘김")
        return

    state.outer_turns += 1
    state.pending_question = None
    state.needs_fix_approval = False

    flags = {"interrupted": False}  # can_use_tool이 의도적으로 거부했는지 표시(예외 판별용)
    server = create_sdk_mcp_server("subtitle_qc", tools=_build_tools(state))
    options = ClaudeAgentOptions(
        tools=[],  # 빌트인 도구(Bash/Read/ToolSearch 등) 전부 끈다 — 이 세 도구만 쓴다
        mcp_servers={"subtitle_qc": server},
        allowed_tools=["mcp__subtitle_qc__run_check"],  # 안전(읽기전용) — 자동승인
        can_use_tool=_make_can_use_tool(state, flags),  # run_fix·ask_human은 여기서 걸러진다
        setting_sources=[],  # 프로젝트 CLAUDE.md·훅·OMC 스킬 안 불러온다 — 최소권한
        skills=[],
        system_prompt=SYSTEM_PROMPT,
        max_turns=MAX_TURNS_PER_CALL,
        max_budget_usd=MAX_BUDGET_USD_PER_CALL,
        resume=state.sdk_session_id,
        cwd=str(REPO_ROOT),
    )

    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        state.log("agent_note", block.text.strip())
                    elif isinstance(block, ToolUseBlock):
                        pass  # 도구 핸들러/can_use_tool이 이미 구체적으로 로그를 남긴다
            elif isinstance(msg, ResultMessage):
                state.sdk_session_id = msg.session_id
                state.total_cost_usd += msg.total_cost_usd or 0.0
                state.total_duration_ms += msg.duration_ms or 0
                usage = msg.usage or {}
                in_tok = usage.get("input_tokens", 0) or 0
                out_tok = usage.get("output_tokens", 0) or 0
                state.total_input_tokens += in_tok
                state.total_output_tokens += out_tok
                state.log(
                    "turn_result",
                    f"{msg.num_turns}턴, ${msg.total_cost_usd:.4f}, {msg.duration_ms}ms, "
                    f"토큰 입력{in_tok}/출력{out_tok}"
                    + (f", 중단: {msg.stop_reason}" if msg.stop_reason else ""),
                    cost_usd=msg.total_cost_usd, duration_ms=msg.duration_ms,
                    input_tokens=in_tok, output_tokens=out_tok,
                )
    except Exception as e:
        # can_use_tool을 interrupt=True로 거부하면 CLI 프로세스가 그 뒤 비정상
        # 종료 코드를 내면서 여기로 예외가 올라온다 — 거부 자체는 의도된 동작이다.
        # flags["interrupted"]로 판별한다(pending_question 유무만으로는 안 된다 —
        # 확인 위반이 전부 SE로 이관돼 물을 게 없는 정상 종료도 pending_question이
        # None이라서 예전 판별식은 그 경우를 오판했다). 아무 인터럽트도 없이
        # 터졌을 때만 진짜 실패로 취급한다(PRD 실패 처리 규칙 — 자동 재시도 안 함).
        if not flags["interrupted"]:
            state.status = "error"
            state.error = f"에이전트 호출 실패: {e}"
            state.log("loop", state.error)
            return
        state.log("loop", f"interrupt 뒤 프로세스 종료 코드(무시함): {e}")

    if state.pending_question is not None:
        state.status = "waiting_for_user"
    elif state.needs_fix_approval:
        state.status = "running"
    elif not state.checked:
        # 검사가 한 번도 성공 못 한 채 턴이 끝났다 — "위반 없음"(정상 완료)과
        # 혼동하면 절대 안 된다(둘 다 violations가 빈 리스트라 이 플래그 없이는
        # 구분 불가능했다). 실제로 겪었다: amazon처럼 프로파일 없는 발주처를
        # 주면 run_check가 도구 에러로 실패하고, 모델이 그 사실을 텍스트로만
        # 설명한 뒤 턴을 끝내는데, 이 분기가 없으면 그대로 "완료(위반 0건)"로
        # 잘못 표시됐다(2026-09-09).
        state.status = "error"
        state.error = "검사를 한 번도 성공하지 못한 채 턴이 끝났습니다 — 도구 실패나 프로파일 문제일 수 있습니다."
        state.log("loop", state.error)
    elif not state.violations:
        state.status = "done"
        state.result = _build_done_result(state)
    else:
        # 모델이 도구를 더 안 부르고 턴을 끝냈는데 위반이 남아 있다 — 안전망으로
        # 강제로 확인 카드를 띄운다(사람 확인 없이 "완료"로 보이면 안 된다).
        # 타이밍류는 여기서도 웹 카드로 안 새고 SE로 나가야 한다(위와 동일 규칙).
        confirm_pending = [v for v in state.violations if v.severity == "confirm"]
        web_violations, video_violations = checker_tools.split_confirm_violations(confirm_pending)
        if video_violations:
            items = []
            for v in video_violations:
                for loc in v.locations:
                    items.append((loc, f"[{v.rule_id}] {v.article} — 에이전트 확인 필요(영상 확인 대상)"))
                    state.dispositioned[_sig(v.rule_id, loc)] = "SE로 이관"
            bookmarks_path = checker_tools.export_bookmarks(Path(state.current_path), items)
            state.se_bookmarks_path = str(bookmarks_path)
            state.log("bookmarks", f"영상 확인 필요 {len(items)}건 -> {bookmarks_path.name}(안전망 경로)")
            state.violations = _refresh_violations(state, state.violations)
            web_violations = [v for v in state.violations if v.severity == "confirm"]
        if web_violations:
            state.pending_question = checker_tools.build_pending_question(
                web_violations, question_id=f"q_fallback_{state.outer_turns}", version=1,
            )
            state.status = "waiting_for_user"
            state.log("loop", "모델이 확인 없이 턴을 끝냈다 — 안전망으로 확인 카드 강제 생성")
        elif not state.violations:
            state.status = "done"  # 전부 SE로 빠지고 남은 게 없다
            state.result = _build_done_result(state)
        else:
            # auto만 남았는데 fix_approved도 아니고 needs_fix_approval도 안 켜졌다 —
            # 모델이 run_fix를 아예 안 불렀다는 뜻. 사람에게 상황을 그대로 보여준다.
            state.needs_fix_approval = True
            state.status = "running"
            state.log("loop", "auto 위반이 남았는데 모델이 run_fix를 안 불렀다 — 승인 대기로 전환")
