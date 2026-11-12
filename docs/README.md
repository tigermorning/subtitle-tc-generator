# 문서 지도

어떤 문서가 무엇의 원본인지, 언제 마지막으로 맞췄는지 적는다. 두 문서가 다르면
**원본 쪽**이 이긴다. 2026-11-11 만들었다.

- «마지막 커밋»은 `git log -1 -- <파일>` 날짜다(2026-11-11 확인).
- «상태»: 현재 = 2026-11-11에 지금 상태와 맞췄다. 낡음 = 아래 이유로 지금과 다른
  곳이 있다. 기록 = 날짜순 역사라 고치지 않는다.

## 원본 표

| 문서 | 무엇의 원본인가 | 마지막 커밋 | 상태 |
|---|---|---|---|
| `CLAUDE.md` | Claude가 지키는 작업 강령(2026-11-08 재작성) | 2026-11-09 | 3절 파이프라인은 코드 순서 — 코드를 설계에 맞추기로 결정(2026-11-11), 아직 안 바꿈 |
| `docs/RULES_ORIGINAL_HISTORY.md` | 옛 작업 규칙 0~18번 전문(예전 `CLAUDE.md`) | 2026-11-08 | 기록. 다른 문서의 «CLAUDE.md 규칙 N»은 이 파일의 번호다 |
| `AGENTS.md` | 다른 AI 도구의 입구 | 2026-09-27 | 낡음: «CLAUDE.md 규칙 0~18번»이라고 적었으나 그 규칙은 지금 `RULES_ORIGINAL_HISTORY.md`에 있다 |
| `README.md`(루트) | 사용법·명령·규정 계층 | 2026-10-16 | «작업 단계»는 코드 순서. 사용자 설계는 `docs/PRD.md` |
| `docs/PRD.md` | 제품 요구사항(문제·대상·설계 순서·자동 확정 기준) | 2026-11-11 고침 | 현재 |
| `docs/MVP.md` | 지금 실제로 되는 것 | 2026-11-11 고침 | 현재(시험은 안 돌림) |
| `docs/HANDOFF.md` | 왜 이렇게 만들었나, 무엇이 비었나. **7절 우선 과제가 최신 결정의 원본** | 2026-11-11 고침 | 2절은 코드 순서(머리에 표시). 7·8절 2026-09-13 수치·결론은 옛 값(표시) |
| `.claude/skills/TC-파형-인아웃/SKILL.md` | TC 인점·아웃점 절차(사람 음성 파형만으로, 도구 `tools/waveform_tc/`) | 2026-11-12 | 현재 |
| `docs/BACKLOG.md` | 날짜순 작업 기록·남은 일 | 2026-09-27 | 낡음: 머리 «마지막 갱신 2026-09-17». 2026-10 이후 결정은 HANDOFF 7절에만 있다 |
| `docs/STAGE_CONTRACTS.md` | 단계별 입출력 약속 | 2026-09-24 | 확인 안 함(2026-11-11) |
| `docs/BENCHMARK_FLITTO_PIPELINE.md` | Judge·Refine 설계 근거 | 2026-11-09 | 현재. 코드 없음 — 절차·프롬프트만(`docs/MVP.md`) |
| `docs/TEAM_RECRUITMENT_PITCH_10MIN.md` | 팀원 모집 발표 | 2026-11-09 | 확인 안 함(2026-11-11) |
| `자막TC생성기-발표문.md`(루트) | 발표 대본 | 2026-11-09 | 처리 순서를 코드 순서로 설명한다. 확인 안 함 |
| `docs/screenshots/SLOTS.md` | 발표 그림 자리 | 2026-11-09 | 2026-09-11 수치는 옛 값(표시) |
| `docs/PR_HISTORY.md`, `docs/AGENT_INCIDENTS.md` | PR·사고 기록 | 2026-09-17 | 기록 |
| `docs/SUBTITLE_EDITOR_PROJECT_BRIEF.md` | 2026-08-11~12 범위 결정 | 2026-09-17 | 기록 |
| `docs/TRANSLATION_ARCHITECTURE.md` | 번역 구조 | 2026-08-14 | 확인 안 함(2026-11-11) |
| `docs/SE_PLUGIN.md`, `docs/SE_WORKFLOW_AUTOMATION.md`, `docs/SUBTITLEEDIT_ARCHITECTURE_ANALYSIS.md` | SubtitleEdit 연동 | 2026-09-10~17 | 확인 안 함(2026-11-11) |
| `docs/COMMERCIALIZATION.md`, `docs/THIRD_PARTY.md` | 상용화 검토·외부 라이선스 | 2026-09-17 | 확인 안 함(2026-11-11) |
| `rules/SCHEMA.md` | 규정 파일 형식 | 2026-09-23 | 확인 안 함(2026-11-11) |
| 비공개 `rules/private/`(저장소 `subtitle-tc-rules`) | 발주처 규정 프로파일, 작업자 실무 자료, se-guide, 코퍼스 원장 | 2026-11-06 | 공개 저장소에 내용을 옮기지 않는다 |

## 깃허브에 없는 자료 (2026-11-11, 이 PC에서 확인)

공개 저장소다. 영상·대사·SRT·정답 자막은 저작권 자료라 **올리지 않는다**. 규정
자료는 비공개 저장소 `rules/private`에만 둔다. «git 밖»은 `.gitignore` 대상이거나
저장소 폴더 밖이라는 뜻이다.

| 자료 | 문서 근거 | 이 PC | git | 비고 |
|---|---|---|---|---|
| 번역 심판 시험 목록 `docs/evidence/judge_injection_set_v2.csv` | `tools/judge_injection/build_set.py` | 있음 | 저장소 | 셀 번호·유형만 |
| 번역 심판 대사 산출물 `.work/judge_injection/` | 같은 파일 머리 주석 | 없음 | git 밖 | 대사. 올리면 안 됨 |
| 번역 심판 설계 `TRANSLATION_CONSTRUCT_DESIGN.md` | 같은 파일 머리 주석(«프로젝트 루트») | 없음(문서 폴더 4단계까지 찾음) | 확인 못 함 | 다른 PC에 있을 수 있음 |
| 정답지 원본 영상 `[습작] SDH+번역/학습완료/` | 비공개 코퍼스 원장 | 없음 | git 밖 | 영상. 올리면 안 됨 |
| 정답 자막 모음 `학습한 TC 및 자막 모음/` | `.gitignore`, 코퍼스 원장 | 없음 | git 밖(비공개 백업은 따로) | 정식 번역문. 올리면 안 됨 |
| 학습 짝 `corpus/pairs/` | `.gitignore` | 없음 | git 밖 | 정답 텍스트. 올리면 안 됨 |
| 드라마B 초안 `.tmp/tc_probe/`, `.tmp/최종초안/` | HANDOFF 7절, 코퍼스 원장 | 없음 | git 밖(`.tmp/` 무시) | 9/13 수치를 다시 낼 재료 |
| 발표 그림 `docs/screenshots/tc-error/`, `generator/` | SLOTS.md | 빈 자리(`.gitkeep`만) | 저장소 | 다른 PC에 있을 것으로 본 기록(SLOTS.md) |
| SubtitleEdit 소스 `subtitleedit-src/` | — | 없음 | git 밖 | 외부 오픈소스 |
| 실행 파일 `dist/자막생성기/` | MVP «GUI 앱» | 있음 | git 밖(`dist/` 무시) | 빌드 결과 |
| VAD 모델 `models/silero_vad.onnx` | `.gitignore` | 있음 | git 밖 | 용량 |
| `../experiments/`(분리 클립 wav·mp4, VAD 검수 묶음) | 저장소 문서에서 언급 못 찾음 | 있음 | 저장소 밖 | 영상·음성. 무엇인지 확인 안 함 |
| se-guide 강의 문서·그림·음성 받아쓰기 | 비공개 저장소 `se-guide/README.md` | 있음 | 비공개 저장소 | 공개 저장소에 옮기지 않음 |

이 PC에 «없음»인 것은 다른 PC에만 있거나 지워졌을 수 있다. 어느 쪽인지는 이 PC에서
확인할 수 없다.
