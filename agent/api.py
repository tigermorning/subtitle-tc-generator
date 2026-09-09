"""FastAPI 오케스트레이션 서버. API_SPEC.md의 계약을 구현한다.

agent/loop.py(Claude Agent SDK)가 실제 계획→도구호출→관찰→다음행동을
돈다. 이 파일은 HTTP 계약을 그 루프에 연결하는 것만 한다 — "다음에 뭘
할지" 판단은 여기 없다(그건 loop.py 안, 진짜 LLM이 한다).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from checker.parsers import parse as parse_srt

from agent import loop
from agent.state import SessionState, load, new_file_id, save, session_dir

app = FastAPI(title="자막 QC 승인 에이전트 (MQ4 데모)")


def _load_or_404(file_id: str) -> SessionState:
    state = load(file_id)
    if state is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return state


@app.post("/api/sessions", status_code=201)
async def create_session(
    file: UploadFile = File(...),
    # 빈 문자열을 기본값으로 둔다 — Form(...)(필수)면 빈 문자열이 왔을 때
    # FastAPI 자체 검증(422)이 우리 핸들러보다 먼저 막아서, 아래 400 분기가
    # 죽은 코드가 된다(2026-09-09, 시험 짜다가 실제로 걸림). 필드가 아예
    # 없을 때는 여전히 422 — "값을 비워 보냄"과 "안 보냄"을 구분하지 않는다.
    platform: str = Form(""),
    kind: str = Form(""),
    language: str = Form(""),
):
    if not file.filename or not file.filename.lower().endswith(".srt"):
        raise HTTPException(status_code=400, detail={"error": "invalid_srt"})
    if not platform or not kind:
        # 사람 개입 지점 1 — 자동 감지 실패 시 반드시 사람이 고른다. 이 데모는
        # 자동 감지 자체를 안 하므로 매번 필수값으로 받는다.
        raise HTTPException(status_code=400, detail={"error": "missing_platform"})

    file_id = new_file_id()
    input_path = session_dir(file_id) / "input.srt"
    with input_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    state = SessionState(
        file_id=file_id, status="running",
        platform=platform, kind=kind, language=language,
        current_path=str(input_path),
    )
    await loop.run_turn(
        state,
        f"srt 파일이 준비됐다. 발주처={platform}, 종류={kind}, 언어={language}. "
        "검사부터 시작해서 필요한 조치를 진행해라.",
    )
    save(state)
    return {"file_id": file_id, "status": state.status}


@app.get("/api/sessions/{file_id}")
async def get_session(file_id: str):
    return _load_or_404(file_id)


@app.post("/api/sessions/{file_id}/approve-fix")
async def approve_fix(file_id: str):
    state = _load_or_404(file_id)
    state.fix_approved = True
    await loop.run_turn(state, "자동 교정 적용을 승인했습니다. 이어서 진행해줘.")
    save(state)
    return {"approved": True, "status": state.status}


@app.post("/api/sessions/{file_id}/answer")
async def answer(file_id: str, payload: dict):
    state = _load_or_404(file_id)
    pq = state.pending_question
    if pq is None or pq.question_id != payload.get("question_id"):
        raise HTTPException(status_code=409, detail={"error": "no_pending_question"})
    if pq.answered:
        # 멱등성 — 같은 질문에 이미 답했으면 재처리 없이 현재 상태를 그대로 준다.
        return state
    if pq.version != payload.get("version"):
        raise HTTPException(
            status_code=409,
            detail={"error": "stale_question", "current_version": pq.version},
        )

    answers = payload.get("answers", [])
    for a in answers:
        sig = f"{a['rule_id']}:{a['cue_index']}"
        state.dispositioned[sig] = a["decision"]
    pq.answered = True
    state.log("ask_human", f"{len(answers)}건 응답 반영")

    summary = ", ".join(f"{a['rule_id']}@{a['cue_index']}={a['decision']}" for a in answers)
    await loop.run_turn(state, f"사용자 응답을 반영했다: {summary}. 남은 위반이 있는지 확인하고 이어서 진행해줘.")
    save(state)
    return state


@app.get("/api/sessions/{file_id}/cue/{cue_index}")
async def get_cue_text(file_id: str, cue_index: int):
    """확인 카드가 실제 무슨 내용을 묻는지 화면에 보여주기 위한 것 — 서버가
    로컬 파일에서 직접 읽어 브라우저로 바로 돌려준다. 에이전트(LLM) 프롬프트는
    이 요청 경로를 절대 거치지 않는다(PRD_MQ4.md 핵심 설계 원칙)."""
    state = _load_or_404(file_id)
    events = parse_srt(Path(state.current_path))
    match = next((e for e in events if e.index == cue_index), None)
    if match is None:
        raise HTTPException(status_code=404, detail={"error": "cue_not_found"})
    return {"cue_index": cue_index, "text": match.text, "start_ms": match.start_ms, "end_ms": match.end_ms}


@app.get("/api/sessions/{file_id}/result")
async def get_result(file_id: str):
    state = _load_or_404(file_id)
    if state.status != "done":
        raise HTTPException(status_code=409, detail={"error": "not_done_yet"})
    return {"output_path": state.current_path, "report": state.result}


@app.get("/api/sessions/{file_id}/bookmarks")
async def download_bookmarks(file_id: str):
    state = _load_or_404(file_id)
    if not state.se_bookmarks_path:
        raise HTTPException(status_code=404, detail={"error": "no_bookmarks"})
    return FileResponse(state.se_bookmarks_path, filename=Path(state.se_bookmarks_path).name, media_type="application/json")


@app.get("/api/sessions/{file_id}/download")
async def download(file_id: str):
    state = _load_or_404(file_id)
    if state.status != "done":
        raise HTTPException(status_code=409, detail={"error": "not_done_yet"})
    return FileResponse(state.current_path, filename=f"{file_id}.srt", media_type="text/plain")


static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
