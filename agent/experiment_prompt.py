"""PRD_MQ4.md "실험 & 평가" — "프롬프트를 바꿔가며 성능 변화를 표로" 실험.

API 서버가 필요 없다 — `agent.loop.run_turn`을 직접 불러서, 실행 중에
`loop.SYSTEM_PROMPT`를 바꿔치기해 같은 srt 파일로 두 버전을 돌린다.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

from agent import loop
from agent.state import SessionState, new_file_id, session_dir

ORIGINAL_PROMPT = loop.SYSTEM_PROMPT

SHORT_PROMPT = """너는 자막 QC 에이전트다. run_check·run_fix·ask_human 도구가 있다.
대사 원문은 못 본다 — 도구가 규칙ID·건수만 알려준다. 위반이 없어질 때까지
알아서 판단해서 처리해라."""

CASES = [
    ("A_기존_상세절차프롬프트", ORIGINAL_PROMPT),
    ("B_짧은프롬프트", SHORT_PROMPT),
]

SRT_PATH = "examples/ko-sdh-sample.srt"


async def drive(state, max_steps: int = 10):
    for _ in range(max_steps):
        if state.status in ("done", "error"):
            return state
        if state.needs_fix_approval:
            state.fix_approved = True
            await loop.run_turn(state, "자동 교정 적용을 승인했습니다. 이어서 진행해줘.")
            continue
        if state.status == "waiting_for_user" and state.pending_question:
            pq = state.pending_question
            answers = []
            for c in pq.cards:
                sig = f"{c['rule_id']}:{c['cue_index']}"
                state.dispositioned[sig] = "승인"
                answers.append(f"{c['rule_id']}@{c['cue_index']}=승인")
            pq.answered = True
            state.pending_question = None
            await loop.run_turn(
                state,
                f"사용자 응답을 반영했다: {', '.join(answers)}. 남은 위반이 있는지 확인하고 이어서 진행해줘.",
            )
            continue
        break
    return state


async def run_one(label: str, prompt_text: str) -> dict:
    loop.SYSTEM_PROMPT = prompt_text
    file_id = new_file_id()
    input_path = session_dir(file_id) / "input.srt"
    shutil.copy(SRT_PATH, input_path)
    state = SessionState(file_id=file_id, status="running", platform="netflix",
                          kind="sdh", language="ko", current_path=str(input_path))
    t0 = time.time()
    await loop.run_turn(
        state,
        "srt 파일이 준비됐다. 발주처=netflix, 종류=sdh, 언어=ko. 검사부터 시작해서 필요한 조치를 진행해라.",
    )
    state = await drive(state)
    wall_s = time.time() - t0
    row = {
        "label": label, "status": state.status, "outer_turns": state.outer_turns,
        "auto_fixed": state.auto_fixed_count, "cards_answered": len(state.dispositioned),
        "cost_usd": round(state.total_cost_usd, 4), "duration_ms": state.total_duration_ms,
        "input_tokens": state.total_input_tokens, "output_tokens": state.total_output_tokens,
        "wall_s": round(wall_s, 1),
    }
    print(row)
    return row


async def main() -> None:
    results = [await run_one(label, prompt_text) for label, prompt_text in CASES]
    loop.SYSTEM_PROMPT = ORIGINAL_PROMPT
    Path(".work/prompt_experiment_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    asyncio.run(main())
