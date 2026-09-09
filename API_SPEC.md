# API_SPEC — MQ4 자막 QC 승인 에이전트

`PRD_MQ4.md` "워크플로 설계"의 트리거~⑥ 단계를 화면과 서버가 주고받는 실제
계약으로 정리한 것. `DECISIONS.md`대로 FastAPI, 세션 상태는 파일 기반이다.

`checker` 실제 연결(`agent/tools.py`)과 Claude Agent SDK 루프(`agent/loop.py`)
둘 다 붙어 있다 — 아래 계약은 화면이 실제로 마주치는 상태다, 모의 데이터가
아니다.

## 세션 모델

```json
{
  "file_id": "f_2f8a...",
  "status": "running | waiting_for_user | done | error",
  "platform": "netflix", "kind": "sdh", "language": "ko",
  "outer_turns": 0,
  "fix_approved": false,
  "needs_fix_approval": false,
  "sdk_session_id": null,
  "total_cost_usd": 0.0,
  "total_duration_ms": 0,
  "dispositioned": {"S02:7": "승인"},
  "violations": [
    {"rule_id": "T16", "article": "Korean TTSG I.13", "count": 4,
     "severity": "auto", "locations": [12, 45]}
  ],
  "pending_question": {
    "question_id": "q_1", "version": 1,
    "cards": [{"rule_id": "S02", "article": "...", "cue_index": 7}],
    "options": ["승인", "거부", "직접수정"]
  },
  "history": [{"loop": 0, "tool": "run_check", "summary": "...", "at": "..."}],
  "result": null
}
```

`status`가 곧 화면이 그릴 상태다 — `PRD_MQ4.md`의 진행 상황 화면
(`running`/`waiting_for_user`/`done`)과 그대로 대응한다.

## 엔드포인트

### `POST /api/sessions`

srt 파일 업로드 + 발주처·종류·언어. 세션을 만들고 첫 에이전트 턴을 실제로
돌린다(모의 데이터 아님) — 그 턴 안에서 `run_check`가 실행되고, 자동 위반이
있으면 `waiting_for_user`(승인 대기), 확인만 남으면 `waiting_for_user`(카드),
없으면 바로 `done`으로 끝날 수 있다.

```
multipart/form-data: file, platform, kind, language
-> 201 {file_id, status}
-> 400 {detail: {error: "invalid_srt" | "missing_platform"}}  # 자동 감지 실패 시 platform/kind 필수(사람 개입 지점 1)
```

**오류 응답은 전부 `{"detail": {...}}`로 감싸인다** — FastAPI의
`HTTPException(detail=...)` 기본 동작이다. 아래 다른 엔드포인트의 4xx/409
예시도 전부 이 형태다(줄여서 `{error: ...}`로만 적은 곳도 실제로는
`{"detail": {"error": ...}}`다).

### `GET /api/sessions/{file_id}`

현재 세션 상태 전체(위 세션 모델)를 반환. 화면이 이걸로 진행 상황·확인
카드·결과를 그린다. 새로고침해도 이 호출 하나로 복구된다(PRD "새로고침해도
카드가 남아 있어야 한다" 요구사항).

```
-> 200 {...세션 모델...}
-> 404 {detail: {error: "not_found"}}
```

### `POST /api/sessions/{file_id}/answer`

확인 카드에 대한 답변 제출.

```json
{"question_id": "q_1", "version": 1,
 "answers": [{"rule_id": "S02", "cue_index": 7, "decision": "승인" | "거부" | "직접수정"}]}
```

**`rule_id`가 필요한 이유**: 같은 큐에 위반이 여러 규칙 동시에 걸리는 게 실제로
흔하다(예: 2번 큐에 C02·S06 동시 위반). `cue_index`만으로 답을 식별하면
한쪽 답이 다른쪽을 덮어쓴다 — 그래서 `(rule_id, cue_index)` 쌍이 답 하나의
식별자다.

```
-> 200 {...갱신된 세션 모델...}
-> 409 {detail: {error: "no_pending_question"}}       # 대기 중인 질문이 없는데 답변 옴
-> 409 {detail: {error: "stale_question", current_version: N}}  # question_id는 맞는데 version이 낡음(PRD "지난 질문임을 알리고 덮어쓰지 않는다")
```

**멱등성**: 같은 `question_id`+`version`에 이미 답이 달려 있으면(제출 버튼
두 번 눌림) 재실행 없이 직전 결과를 그대로 반환한다 — 새로 처리하지 않는다.

### `POST /api/sessions/{file_id}/approve-fix` (사람 개입 지점 2 전용)

최초 자동교정 적용 전 1회 동의. 이후 같은 세션의 `run_fix` 재호출은 이
엔드포인트를 다시 안 거친다. 세션 모델의 `needs_fix_approval: true`가
화면이 이 버튼을 보여줄 신호다 — 자동 가능한 위반이 남았는데 아직 동의를
안 받은 상태를 뜻한다.

```
-> 200 {approved: true}
```

### `GET /api/sessions/{file_id}/result`

`status == "done"`일 때만 의미 있다. 수정된 srt 다운로드 링크 + 리포트.

```
-> 200 {output_path, report: {fixed: N, se_review: M, se_bookmarks_path,
                              remaining: 0, loop_count, cost_usd, duration_ms}}
-> 409 {detail: {error: "not_done_yet"}}
```

`se_review`는 영상 확인이 필요해 SE 북마크로 이관된 건수다(웹 카드로 처리한
`fixed`와 별개 — "고쳤다"와 "SE로 넘겼다"를 안 섞는다).

### `GET /api/sessions/{file_id}/download`

`status == "done"`일 때만 수정된 srt 파일 자체를 내려받는다.

```
-> 200 (text/plain, .srt 파일)
-> 409 {detail: {error: "not_done_yet"}}
```

### `GET /api/sessions/{file_id}/bookmarks`

`se_review > 0`일 때만 의미 있다. SE가 인식하는 북마크 파일
(`checker/bookmarks.py` 포맷 — 사용자 실사용 버전인 SE 4.0.15 기준,
`<srt파일명>.SE.bookmarks`)을 내려받는다.

```
-> 200 (application/json, .bookmarks 파일)
-> 404 {detail: {error: "no_bookmarks"}}
```

### `GET /api/sessions/{file_id}/cue/{cue_index}`

확인 카드가 실제로 무슨 내용을 묻는지 보여주기 위한 것 — **에이전트(LLM)는
이 경로를 거치지 않는다.** 서버가 현재 작업본(`current_path`)에서 직접
읽어 화면에만 돌려준다(PRD_MQ4.md 핵심 설계 원칙).

```
-> 200 {cue_index, text, start_ms, end_ms}
-> 404 {detail: {error: "cue_not_found"}}
```

## 오류 처리 원칙

`PRD_MQ4.md` "실패 처리 규칙"을 API 층에서도 지킨다 — 어떤 엔드포인트도
실패를 자동 재시도하지 않는다. 실패하면 `status: "error"`로 두고 원인을
`history`에 남긴다. 다음 단계(실제 엔진 연결)에서 `checker` 예외를 이
계약으로 매핑한다.
