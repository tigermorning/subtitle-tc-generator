# 플리토(Flitto) 벤치마크 분석 — 자가교정(Judge & Refine) 파이프라인과 자막 상태 머신

> 2026-11-09 작성. 플리토의 공개 오픈소스 두 건을 전수 분석해 이 저장소의 자막 번역 워크플로에
> 이식 가능한 설계만 뽑아 정리한 문서다. 근거 원문은 아래 저장소들이며, 이 문서의 설계는
> CLAUDE.md의 5대 절대 강령 **아래에** 놓인다 — 어떤 항목도 강령을 약화시키지 않는다.

## 0. 분석 대상과 근거

| 저장소 | 성격 | 이 문서에서 가져온 것 |
|---|---|---|
| [`flitto/speech-to-sft-ablation-paper`](https://github.com/flitto/speech-to-sft-ablation-paper) | EMNLP 2026 Industry Track 논문 재현 패키지(한국어 의료·금융 음성 → QA SFT 파이프라인). Phase 2 judge·refine 프롬프트를 **원문 그대로** 공개 | 4차원 채점 → 판정 → Refine 루프 전체 구조, 언어 락(STRICT), 임계치 규칙, 편향 완화 설계 |
| [`flitto/rtt_sdk`](https://github.com/flitto/rtt_sdk) | 플리토 실시간 통·번역 SDK(Android/iOS, `chat-guest`) | 실시간 자막의 메시지 상태 모델(`listType`) — 자막 상태 머신의 원형 |

두 저장소 모두 공개 자산이며(CC BY-NC 4.0 등), 여기서는 **설계 패턴의 이식**만 하고
코드·프롬프트를 그대로 복제하지 않는다. 자막 도메인에 맞게 재작성한 부분은 본 문서 기준이다.

---

## 1. 플리토 Phase 2 파이프라인이 하는 일 (논문 저장소 근거)

플리토의 음성→QA 파이프라인은 Phase 0(전사 정제) → Phase 1(생성) → **Phase 2(품질 정제)**로
구성되고, Phase 2가 곧 "측정 도구"다. 공개된 `prompts/pipeline/` 세 파일이 전부다.

### 1.1 Judge (`prompts/pipeline/phase2_judge.md`)

- 정답지 없는 생성물을 원문(source) 대조로만 평가한다. 4차원, 각 0–10점:
  `factcheck`(사실 정확성), `consistency`(내적 일관성), `source_verify`(원문 검증 가능성),
  `decontextualized`(맥락 얽힘 제거 — 스타일 차원).
- **핵심 규칙 — 원문 추적 불가면 0점**: 질문의 주제가 원문에서 추적되지 않으면 답의 품질과
  무관하게 `source_verify`를 0으로 매긴다. *"External knowledge should only DEEPEN answers,
  never CREATE new topics."* — 외부 지식은 답을 **보강할** 뿐 **새 주제를 만들지** 못한다.
- 차원 간 독립성 명시: `source_verify=10`이면서 `decontextualized=3`일 수 있다. 각자 따로 매긴다.
- 판정(verdict) 규칙:

| 조건 | 판정 |
|---|---|
| 모든 차원 ≥ 7.0 | `pass` |
| 하나라도 < 4.0 | `fail` |
| 그 외 | `human_review` |

- 운영 설계: 심사 모델(Open 계열 GPT-5.2)과 생성 모델(Anthropic·Xiaomi 계열)의 **패밀리 분리**로
  자기 평가(self-evaluation)를 구조적으로 차단. 5-저지 앙상블 + 셀 블라인드(조건 정보 은닉) +
  랜덤 셔플 + 엄격 JSON 스키마가 편향 완화의 기본기다(`prompts/llm_judge_rubric.md` 참조).

### 1.2 Refine (`prompts/pipeline/phase2_refine.md`)

- Judge 점수와 reasoning을 **그대로 입력**받아 실패 항목만 고친다. 절차: 각 차원 점수·사유 분석 →
  저점의 근본 원인 특정 → 관련 부분 재작성 → 원문으로 검증 가능한지 확인.
- **언어 락(STRICT)**: 출력은 반드시 입력과 **같은 언어 전체**로 쓴다. 외국어 담화표지 삽입 금지
  (한국어 출력에 首先/其次/最后, first/second 등 금지), 나열은 원어의 자연스러운 연결어로.
- **재작성도 원문 미지원 내용 생성 금지**: "Do not introduce new factual claims not supported
  by the source." Refine은 창작 단계가 아니라 교정 단계다.
- **최대 2회 반복**: Refine 1회마다 Judge 재평가를 거치고, 모든 차원이 ≥ 7.0에 도달하면 조기 종료.
  2회 실패 시 그 항목은 `fail` 처리되어 파이프라인에서 배제된다(사람 손으로 넘어간다).

### 1.3 우리가 배울 점 — QA와 자막의 동형성

| 플리토 Phase 2 (QA) | 이 저장소 (자막) |
|---|---|
| 원문 문서(source document) | 원어 스크립트 + 원어 TC(인점·아웃점) |
| `source_verify` — 원문 추적 불가 0점 | 헌법 2조 불가감·불가증 — 원문에 없는 것을 더하거나 원문 정보를 빼는 것 탈락 |
| 언어 락(STRICT) | 타겟 언어 락 — 한국어 납품물에 원어 잔어·번역투 담화표지 반입 금지 |
| Refine ≤ 2회 후 fail 배제 | Refine ≤ 2회 후 `human_review` 승격 |
| Generator–Judge 패밀리 분리 | 생성에 쓴 모델/세션과 심사를 분리 — 자기 번역을 자기가 채점하지 않게 |

---

## 2. 자막용 4차원 LLM-Judge 루브릭 (본 저장소 표준)

플리토의 4차원(factcheck·consistency·source_verify·decontextualized)은 QA 데이터용이다.
자막의 물리법칙(헌법 1조)과 규범 분리(헌법 4조)를 반영해 아래 4차원으로 치환한다. 각 0–10점.

### ① faithfulness (원문 불가감·불가증 기반 정합성) — 헌법 2조
- 원어 스크립트의 모든 팩트·감정 뉘앙스·복선 정보가 보존됐는가. 임의 창작, 원문에 없는 사족,
  핵심 정보 누락은 **0점 탈락** (플리토의 "원문 추적 불가 → 0점" 규칙의 자막판).
- 원문 없이는 검증할 수 없는 내용이 하나라도 있으면 이 차원은 pass 조건을 벗어난다.

### ② tc_sync (인점·아웃점 싱크 및 컷 일치) — 헌법 1조
- 인점이 발화 시작점과 일치하고, 아웃점이 최소 간격·최소 표시 시간·장면전환 경계를 지키는가.
- `--lock-timecodes` 파일에서 TC가 0.1초라도 변했으면 이 차원은 즉시 fail이다. Judge는
  TC를 점수화하기 전에 **먼저 TC 무결성을 확인**한다 — 점수로 사정할 문제가 아닌 위반을
  점수로 뭉개지 않게.

### ③ readability_cps (글자 수·줄바꿈·CPS 제약) — 헌법 3조
- 한국어 납품물 기준의 줄당 글자 수, 줄바꿈 호흡(의미단위 분할), 초당 글자 수(CPS)가
  발주처 프로파일 규정 안에 있는가. 원어 스크립트에 한국어 규정을 들이대지 않는 것도 검증한다.

### ④ naturalness (한국어 구어체 자연스러움)
- 맥락·감정선에 맞는 자연스러운 한국어 입말 의역인가. 단어 대 단어 직역, 번역투, 외국어
  담화표지(먼저/둘째 대신 首先 등)가 남아 있으면 깎인다. 플리토 Refine의 언어 락이 이 차원의
  기반이다.

판정은 플리토와 동일한 임계치를 쓴다: **모든 차원 ≥ 7.0 → pass, 하나라도 < 4.0 → fail(Refine),
그 외 → human_review.** 점수는 판정 근거로 쓰지만 최종 납품 기준은 사람이다(헌법 5조
"확실한 근거와 추정의 분리") — Judge는 사람이 검토할 지점을 짚어 주는 정밀 필터다.

---

## 3. 자가교정(Refine) 루프 설계

```
            ┌──────────────────────────────────────────────┐
            ▼                                              │
  [Generate] 번역 생성          ※ 생성이 끝난 자막이 곧바로 결과물이 아니다
            │
            ▼
  [Judge] 4차원 검수 (faithfulness / tc_sync / readability_cps / naturalness)
            │  각 0–10점 + 차원별 reasoning
            ├─ 모든 차원 ≥ 7.0 ──────────────▶ [pass] 사람 최종 검수로 납품 후보
            │
            ├─ 하나라도 < 4.0 ─▶ [Refine 1] Judge reasoning 반영 자가교정
            │                                   │
            │                                   ▼
            │                          [Judge 재평가] ── pass ──▶ 위와 동일
            │                                   │
            ├─ 그 외 (4.0–6.9) ─▶ human_review ─┘ (루프를 돌지 않고 사람에게)
            ▼
  [Refine 반복 한도 = 2회]
            │
            └─ 2회 실패 ─▶ human_review (자가교정을 포기하고 사람에게 승격)
```

루프의 규칙(플리토 phase2_refine.md에서 이식, 자막 도메인 재규정):

1. **Refine은 Judge reasoning 입력 필수**: 점수만 보고 고치지 않는다. 차원별 사유를 분석해
   저점의 근본 원인(오역, 정보 누락, TC 위반, CPS 초과, 번역투)부터 특정한다.
2. **타겟 언어 락(STRICT)**: 수정 결과는 한국어 납품물 기준으로 전부 한국어다. 원어 잔어,
   외국어 담화표지, 번역투 연결어를 새로 넣지 않는다.
3. **원문 미지원 내용 생성 금지**: Refine은 창작이 아니다. 원문에 근거 없는 사실을 새로
   넣는 수정은 그 자체로 faithfulness 위반이다.
4. **TC는 Refine 대상이 아니다**: `--lock-timecodes` 파일에서 tc_sync가 fail이면 텍스트를
   압축해 맞추는 방향으로만 고친다(헌법 1조). 인점·아웃점을 움직이는 "수정"은 Refine이 아니라
   규정 위반이다.
5. **조기 종료**: 재평가에서 모든 차원이 ≥ 7.0이면 즉시 루프를 닫는다. 2회까지 도니까
   시도 자체가 낭비가 되지 않게.
6. **기록 남기기**: 각 회차의 Judge JSON(점수+reasoning)을 남겨 사람 검토자가 Refine의
   근거를 그대로 볼 수 있게 한다.

---

## 4. 자막 상태 머신 (rtt_sdk 벤치마크에서 이식)

`flitto/rtt_sdk`의 `chat-guest` SDK는 실시간 발화가 어떤 상태를 거쳐 확정되는지를
`listType`으로 공개한다:

| listType | 의미 (SDK 원문) | 자막 상태 머신에서의 역할 |
|---|---|---|
| `realtime` | 실시간 부분 발화 (real-time partial utterance) | **임시 자막** — 아직 확정 아님. 화면에 먼저 띄우되 내용이 바뀔 수 있음 |
| `append` | 현재 발화의 최종 결과 (final result for the current utterance) | **확정 자막** — 이 발화의 텍스트·TC 확정 |
| `update` | 수정·갱신된 메시지 (corrected/updated message) | **문맥 소급 교정** — 이후 문맥을 반영해 이전 확정분을 갱신 |
| `renew` | 최초 로딩 메시지 | 세션 이력 로드 (자막 파일 열기에 상응) |
| `translation` | 번역 메시지 | 타겟 언어 스트림 (번역 자막 트랙에 상응) |

이를 오프라인 자막 제작 워크플로에 대응시키면 자막 한 칸은 아래 상태를 거친다:

```
realtime (임시) ──▶ append (확정) ──▶ update (문맥 소급 교정)
                                        │
                                        └─ update의 범위: 텍스트만. TC는 append 시점에
                                           확정된 인점·아웃점을 유지한다 (헌법 1조).
```

- **realtime → append**: 발화(원어 문장) 경계가 확정되는 시점. 자막에서는 resplit·TC 확정 단계
  (헌법 3조 파이프라인의 ④⑤)에 상응한다.
- **append → update**: 뒤 문맥이 붙은 뒤에야 보이는 어색함(대명사 처리, 호칭 일관성, 번역투)을
  **소급해서** 고치는 단계. Judge·Refine 루프는 이 update 단계에서 돈다 — 한 칸만 보고
  끝내지 않는 이유다.
- **update의 한계**: TC는 소급하지 않는다. 실시간 SDK에서도 update는 텍스트 갱신이지
  타임스탬프 재배치가 아니다(`ChatHistoryItemEntity`의 `timestamp`는 append 시점 값).
  이는 헌법 1조의 "받은 타임코드 불가침"과 정확히 만난다.

---

## 5. 이 저장소에의 적용 — 무엇을 어디에 두는가

| 자산 | 위치 |
|---|---|
| 실전 작업 가이드(클로드 코드가 호출) | `.claude/skills/플리토-자가교정-파이프라인/SKILL.md` |
| Judge 프롬프트 템플릿 | 같은 스킬 내 `prompts/subtitle_judge.md` |
| Refine 프롬프트 템플릿 | 같은 스킬 내 `prompts/subtitle_refine.md` |
| 기존 품질 지표 문서와의 연결 | `.claude/skills/번역-품질-지표/SKILL.md` "LLM-as-judge" 절 갱신 |
| 기본 작업 워크플로 규정 | 루트 `CLAUDE.md` 6절 |

**원칙 확인**: 이 문서와 스킬은 코드가 아니라 클로드 코드가 읽는 지침이다. 기존 코드와
1,240여 개 테스트는 전혀 건드리지 않으며, 5대 헌법은 한 글자도 바뀌지 않았다. Judge·Refine은
헌법 위에서 도는 검수 절차일 뿐, 헌법을 대체하거나 완화하지 않는다.
