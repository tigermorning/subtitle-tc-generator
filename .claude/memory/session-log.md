<!--
project-session-memory 스킬의 정제된 누적 요약 파일입니다.
새 세션이 시작될 때 SessionStart 훅(.claude/hooks/session-memory-start.sh)이
이 파일 내용과 .claude/memory/inbox/의 미정리 캡처를 컨텍스트로 불러옵니다.
inbox를 정리할 때 이 파일 아래에 날짜와 함께 핵심만 append하세요.
-->

## 2026-08-30

- 저장소 전체(커밋 메시지 전량·코드 주석·문서·파일명/식별자)를 한국어/영어
  언어 혼용 관점에서 감사함 — **혼용 없음.** "한국어 서술 + 영어 기술 용어"
  스타일로 일관됨을 확인. 읽기 전용 조사였고 파일 변경 없음.
- 그 감사 중 `AGENTS.md`가 CLAUDE.md 규칙 개수를 "10개"로 적어 둔 게 실제
  개수(규칙 0~17번, 18개)와 어긋난 걸 발견 → 수정하고 커밋(`f53e7b0`).
  CLAUDE.md에 새 규칙이 추가될 때마다 이 문서가 같이 낡을 수 있으니, 다음에
  규칙 번호가 또 어긋나 있으면 그때도 그냥 고치면 됨(별도 검토 불필요).
- push 시 원격에 먼저 올라온 커밋 5개(BACKLOG.md·HANDOFF.md·
  corpus_status.yaml 갱신 + 이 session-memory 훅 자체의 설치 커밋)와 충돌
  없이 병합함(`78b58a4`) — 파일이 겹치지 않아 별문제 없었음.
- `project-session-memory` 스킬(SessionStart/SessionEnd 훅)이 이 세션 도중
  원격에서 병합되어 들어옴. 훅 동작을 코드 읽고 확인함: SessionEnd는
  transcript 꼬리를 `.claude/memory/inbox/<session_id>.md`로 잘라 저장하고
  로컬 커밋만 함(push 안 함 — 무인 push는 안전 분류기가 막았다고 주석에 있음).
  SessionStart는 inbox와 이 파일을 컨텍스트로 불러오고, 정리는 다음 세션의
  Claude 판단에 맡김. 지금 이 항목이 그 "정리해서 append" 작업의 첫 사례.
- SessionEnd 훅이 로컬에만 커밋해 둔 것(`bd42929`)과 원격에 새로 올라온
  커밋들(`docs/AGENT_INCIDENTS.md` 10번 사고 기록, README.md·MVP.md·
  CORPUS_TITLES.md의 `genre_maturity` 언급 추가)을 두 차례에 걸쳐 병합·
  push함(`032c03b`, `e0ce389`) — 전부 겹치는 파일이 없어 충돌 없었고, 매번
  `tests/run_tests.py` 801건 통과를 확인한 뒤 올림.
- 정리 끝난 inbox 캡처 파일(`241feb5d-...md`)은 위 항목들에 이미 반영된
  뒤 삭제하고 커밋·push함(`b509e8b`) — 훅이 지시한 "반영 후 inbox 삭제"
  절차를 실제로 밟은 첫 사례.
- `docs/AGENT_INCIDENTS.md` 10번 사고와 "공통점" 절을 사용자에게 요약해
  전달함(내용은 그 문서 자체에 이미 있으니 여기 중복 기록하지 않음 —
  필요하면 원문 참고).
