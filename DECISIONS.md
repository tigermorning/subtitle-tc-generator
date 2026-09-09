# DECISIONS — MQ4 자막 QC 승인 에이전트

`PRD_MQ4.md`를 구현하기 전 정한 것들. 근거가 바뀌면 여기부터 고치고 PRD는
그 결과만 따라간다(`docs/PRD.md`의 문서 관계와 같은 방식).

## 1. 실행 엔진 — Claude Agent SDK (Python)

**후보**: Claude Agent SDK / Claude CLI(subprocess) / OpenCode CLI(subprocess)

**선택**: Claude Agent SDK.

**이유**: 이 저장소가 이미 Python이다(`checker/`, `app/`). SDK는 같은 프로세스
안에서 `checker`를 라이브러리로 직접 부를 수 있어 서브프로세스 오버헤드·JSON
파싱 계층이 없다. `canUseTool`/`can_use_tool` 콜백으로 사람 개입 지점(카드
승인)을 자연스럽게 구현할 수 있다.

## 2. 웹 프레임워크 — FastAPI

**후보**: FastAPI / Flask / 기타

**선택**: FastAPI.

**이유**: `korean-subtitle-corrector`(`subtitle_corrector/api.py`)가 이미
FastAPI다 — 두 프로젝트가 라이브러리 관계로 이미 연결돼 있으므로(`CLAUDE.md`
규칙0) 같은 스택을 쓰면 두 저장소를 오가는 사람의 인지 비용이 준다. 비동기
지원이 SDK의 `query()` 스트림·대기 콜백 흐름과 잘 맞는다.

## 3. 세션 상태 저장 — 파일 기반(JSON), `.work/` 관례 확장

**후보**: 파일 기반 JSON / SQLite

**선택**: 파일 기반.

**이유**: `docs/PRD.md`가 이미 회차마다 `.work/`에 JSON을 남기는 관례를
정해 놨다(`NN-generate.srt`, `manifest.json` 등). 그 패턴을 세션 상태
(`waiting_for_user`/`running`, `loop_count`, `pending_question`)까지
그대로 확장한다 — `CLAUDE.md` 규칙17("손대기 전에 이미 답이 있는지부터
본다")과 같은 이유로, 새 저장 방식을 만들지 않고 이미 있는 것을 쓴다.
MVP 범위(단일 사용자, 동시 세션 적음)에서 SQLite는 과설계다.

## 4. 코드 위치 — 새 최상위 디렉터리 `agent/`

**후보**: `agent/` 신설 / `checker/` 내부 서브모듈

**선택**: `agent/` 신설.

**이유**: `checker/`·`app/`과 나란한 층위 — 오케스트레이션(에이전트 루프·웹
서버·세션 상태)은 검사·교정 로직(`checker/`)과 관심사가 다르다. `checker/`
안에 넣으면 "결정론적 규칙 엔진"과 "LLM 오케스트레이터"의 경계가 코드
구조에서부터 흐려진다 — PRD의 핵심 설계 원칙(에이전트는 대사 원문을 못
본다)을 지키려면 이 경계가 디렉터리 단위로도 분명해야 한다.

```
agent/
  api.py       FastAPI 앱 — 업로드·진행상황·확인카드·결과 엔드포인트
  loop.py      에이전트 루프(계획→도구호출→관찰→다음행동), Claude Agent SDK 연결
  tools.py     checker를 감싸는 public wrapper (run_check/run_fix/run_korean_review)
  state.py     세션 상태 저장/복원 (.work/agent-session/<file_id>.json)
  static/      데모용 최소 프런트(업로드 폼 · 확인카드 화면)
```
