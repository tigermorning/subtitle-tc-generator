# README — MQ4: 자막 QC 승인 에이전트

[Main Quest 4](https://app.notion.com/p/Main-Quest-4-3d58820152dc80318287cf325709bc69)
제출물. `subtitle-tc-generator`(이 저장소)의 규정검사 엔진(`checker/`) 위에
Claude Agent SDK로 계획→도구호출→관찰→다음행동 루프를 얹은 것 — `agent/`
디렉터리 전부가 이 제출물의 코드다. 설계 배경·요구사항 대응은
[PRD_MQ4.md](PRD_MQ4.md), 계약은 [API_SPEC.md](API_SPEC.md), 구현 결정은
[DECISIONS.md](DECISIONS.md), 실측 결과는 [EVALUATION.md](EVALUATION.md)에
있다. 이 문서는 **실행 방법만** 다룬다.

## 무엇을 하는가 (한 줄)

srt 파일 + 발주처/종류/언어를 받아 규정 위반을 검사하고, 자동 교정 가능한
건 사람 승인 후 적용하고, 텍스트만으로 판단 가능한 나머지는 확인 카드로
사람에게 묻고, **영상·TC 확인이 필요한 위반은 SE 북마크 파일로 내보내
SubtitleEdit에서 이어서 보게** 한다.

## 사전 준비

- Python 3.12+
- 이 저장소의 `checker/` 의존성이 이미 깔려 있어야 한다(`pip install -r
  requirements.txt`, 저장소 루트 README 참고)
- Claude Agent SDK 인증: **API 키를 따로 안 넣는다.** 로컬 `claude` CLI가
  로그인돼 있으면(`claude login`, 이 세션이 이미 그 상태로 돈다) SDK가 그
  인증을 그대로 쓴다 — `ANTHROPIC_API_KEY` 환경변수는 필요 없다(직접 확인함,
  이 세션에도 그 값이 없다). `claude` CLI가 PATH에 있어야 한다.

```bash
pip install -r requirements-agent.txt
```

## 로컬 실행

```bash
python -m uvicorn agent.api:app --port 8765
```

브라우저로 `http://127.0.0.1:8765` 접속 — srt 파일 올리고 발주처/종류/언어
고른 뒤 "검사 시작". 이후 화면에 뜨는 대로: 자동교정 동의 → 확인 카드 응답
(대사 원문이 카드마다 같이 뜬다) → 완료되면 결과 srt 다운로드 / SE 북마크
다운로드.

`.claude/launch.json`에 `mq4-agent` 설정이 이미 있다 — Claude Code의
`preview_start`로도 띄울 수 있다.

## 공개 URL로 확인하고 싶다면

계정 없이 바로 되는 방법(임시, 세션 종료 시 사라짐):

```bash
winget install --id Cloudflare.cloudflared -e
cloudflared tunnel --url http://127.0.0.1:8765
```

출력에 찍히는 `https://<임의문자열>.trycloudflare.com`이 공개 URL이다.
**제출 시점의 캡처본은 이 방식으로 실제 접속해서 남긴 것**이다
(`EVALUATION.md` 참고). 영구 URL이 필요하면 Render/Railway 같은 무료 PaaS에
직접 배포한다 — 계정 생성이 필요해 이 세션이 대신 하지 못했다.

## 평가 재현

```bash
python -m uvicorn agent.api:app --port 8765   # 별도 터미널
python agent/eval.py
```

실제 코퍼스(`학습한 TC 및 자막 모음/` — 저작권 있는 정식 자막이라 이 저장소엔
없다, 로컬 전용) 6편을 끝까지 돌리고 정답지와 역대조까지 한다. 결과는
`EVALUATION.md`에 이미 반영돼 있다.

## 저장소 구조 (`agent/`)

```
agent/
  api.py         FastAPI 앱 — 업로드·진행상황·확인카드·결과·북마크 엔드포인트
  loop.py        에이전트 루프 — Claude Agent SDK, can_use_tool로 사람 개입 지점 구현
  tools.py       checker를 감싸는 public wrapper(run_check/run_fix) + 영상필요 위반 판정
  mcp_server.py  독립 MCP 서버(확장) — 같은 tools.py를 표준 MCP로 노출
  state.py       세션 상태 저장/복원 (.work/agent-session/<file_id>/state.json)
  eval.py        코퍼스 평가 스크립트(재현용)
  static/        최소 프런트(업로드 폼 · 확인카드 화면)
```

## 확장 — 독립 MCP 서버

`agent/mcp_server.py`는 `agent/tools.py`(같은 checker 래퍼)를 우리 웹앱이
아니라 **표준 MCP**로 노출한다. Claude Desktop·Claude Code·다른 에이전트가
설정에 등록만 하면 이 저장소 밖에서도 "이 srt 검사해줘"를 도구로 쓸 수 있다.

```bash
python -m agent.mcp_server    # stdio, 직접 실행하면 대기만 한다(정상)
```

Claude Code에 등록하려면(`.mcp.json` 또는 `claude mcp add`):

```json
{"mcpServers": {"subtitle-qc": {"command": "python",
                                 "args": ["-m", "agent.mcp_server"],
                                 "cwd": "<이 저장소 절대경로>"}}}
```

도구 3개: `check_subtitle`·`fix_subtitle`·`export_se_bookmarks`. 대사
원문은 여기서도 안 돌려준다 — 핵심 설계 원칙은 노출 경로가 바뀌어도 그대로다.
실제 mcp 클라이언트(stdio)로 붙어 `check_subtitle`(9종 위반 정확히 검출)·
`fix_subtitle`(2개 규칙 실제 적용) 둘 다 호출까지 확인했다.

## 알려진 한계 (숨기지 않고 남긴다)

- **"직접수정" 선택지가 실제로 텍스트를 안 바꾼다** — 승인/거부와 동일하게
  처리된다(disposition만 기록). 실제 텍스트 편집 반영은 미구현.
- **`run_korean_review`(한국어 교정기 연동) 도구 미구현** — PRD엔 계획돼
  있으나 코드가 없다. "도구 2개 이상" 조건은 `run_check`/`run_fix`로 이미
  충족한다.
- **SE 북마크는 사용자가 육안으로 직접 확인함**(2026-09-09) — 처음엔 두 번
  틀렸다. ① 파일명이 `<srt>.bookmarks`였는데 SE는 `<srt>.SE.bookmarks`만
  찾는다. ② 그다음 v5.2(RC, 최신 소스 클론) 포맷(`ms`+`forced` 키)으로
  고쳤는데, 정작 사용자 실사용 버전은 **4.0.15**(`CLAUDE.md` "SE 4.x")라
  그 필드들을 모른다 — SE 소스를 태그별로 대조해 4.0.15 실제 포맷
  (`{"bookmarks":[{"idx":i,"txt":"..."}]}`, 0-기준, ms·forced 없음)으로
  되돌리자 바로 떴다. `write()`는 이제 이 버전을 기준으로 한다.
- **에이전트 서버 코드에 아직 테스트가 없다** — 이 저장소의 `tools/hooks/
  pre-commit`이 커밋 전 테스트를 요구하는데(`CLAUDE.md` 규칙9), `agent/`
  쪽 테스트는 아직 `tests/`에 없다. 커밋하려면 이것부터 채워야 한다.
- **세팅을 바꿔가며 비교한 실험이 아직 없다** — `EVALUATION.md`의 6편은
  전부 같은 프롬프트·같은 모델로 돌렸다.
