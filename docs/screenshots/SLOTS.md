# 발표용 스크린샷 자리 (비어 있음 — 다른 PC에서 채운다)

2026-11-09 아이펠 PC를 찾아봤지만 아래 그림은 없었다(저장소·원격 브랜치 5개·사용자 문서/사진/바탕화면/다운로드).
다른 PC에 있을 것으로 보고 **자리만** 만들어 둔다. 파일을 아래 이름 그대로 넣으면 발표 문서의 그림 칸이 채워진다.

| 폴더 / 파일 | 들어갈 그림 | 쓰이는 곳 |
|---|---|---|
| `tc-error/01.png` ~ `05.png` | SubtitleEdit 파형 캡처 — 진한 초록 선 = 우리 인점, 파란 선 = 정답(작업자) 인점. 오차가 보이는 장면 | 발표문 "TC 정확도" 대목, 피칭 Slide 5 |
| `generator/01_main.png` | PySide6 자막 TC 생성기 메인 화면 | 발표문 파이프라인 뒤, 피칭 Slide 3 |
| `generator/02_result.png` | 생성 결과(자막 목록·검사 결과) 화면 | 같은 곳 |

- 장 수가 다르면 번호만 늘리거나 줄이고, 발표 문서의 그림 줄도 같이 맞춘다.
- 미공개 영상 장면이 보이는 캡처는 커밋 전에 가리거나 공개 가능한 자료로 바꾼다(`01_upload.png` 데모의 경고와 같은 이유).
- 그림 옆에 붙일 수치(기록상, `docs/HANDOFF.md` 2026-09-11 실측, 드라마B E02·E03 진짜 짝): 인점 오차 중앙값 79 / 68ms, 100ms 안 55 / 58%, 아웃점 오차 중앙값 139 / 155ms. 〔2026-09-11 측정, 이후 개선(2026-09-30~10-16 커밋)이 반영되지 않은 옛 값 — 최신본 미측정. 발표에서 지금 값으로 인용하지 않는다(`docs/HANDOFF.md` 7절).〕

## 다른 PC에서 채우는 법

### Claude Code에 붙여 넣을 명령문

```text
자막 TC 생성기 발표용 스크린샷을 채우려고 해. 아래 순서대로 해 줘.

1. subtitle-tc-generator 저장소 위치를 찾아서(예: C:\Users\user\Documents\subtitle-tc-generator) `git pull origin master` 해 줘. 최신 커밋에 bad16a0 "docs: 발표용 스크린샷 자리(TC 오차·생성기 화면)를 만든다"가 들어왔는지 확인해.

2. docs/screenshots/SLOTS.md 를 읽어. 채울 자리는 두 가지야.
   - tc-error/01.png ~ 05.png : SubtitleEdit 파형 캡처. 진한 초록 선이 우리 인점, 파란 선이 정답(작업자) 인점이고 그 차이(오차)가 보이는 장면.
   - generator/01_main.png, 02_result.png : PySide6 자막 TC 생성기 화면(메인, 생성 결과).

3. 이 PC에서 후보 그림을 찾아 줘. 사진·바탕화면·다운로드·문서·OneDrive·저장소 폴더(.venv, site-packages, se-guide 강의 자료 그림은 제외)에서 2026-08 이후 png/jpg를 찾고, PC 화면 캡처 크기(가로가 넓은 것)를 우선으로 봐. 저장소의 .claude/skills/하드섭-TC-자막-추출/SKILL.md 에 "SE 스크린샷 5건 실측"이 기록돼 있으니 그 작업 근처 폴더(.tmp 등 git이 무시하는 곳 포함)도 봐.
   후보는 직접 열어 보고, 파일 경로·날짜·크기·무엇이 보이는지를 표로 보여 준 다음 어느 것을 쓸지 나한테 물어봐. 내가 고르기 전에는 복사하지 마.

4. 생성기 화면 캡처가 없으면, 저장소의 launcher.py 로 앱을 띄워서 새로 찍을 수 있는지 먼저 물어봐.

5. 내가 고른 그림을 SLOTS.md 의 이름 그대로 docs/screenshots/ 아래에 복사해. 원본 파일은 옮기거나 지우지 말고 복사만 해. 미공개 영상 장면·대사가 보이면 커밋 전에 나한테 알려 줘(가릴지, 다른 그림으로 바꿀지 내가 정함).
   장 수가 5장과 다르면 자막TC생성기-발표문.md 와 docs/TEAM_RECRUITMENT_PITCH_10MIN.md 의 [그림 자리] 줄 번호도 맞춰 줘.

6. python tests/run_tests.py 가 전부 통과하는지 확인하고, 커밋 메시지 초안과 바뀐 파일 목록을 보여 줘. 커밋과 push는 내가 "커밋하고 push 해"라고 할 때만 해.
```

### 직접 할 때 (PowerShell)

그림을 이미 골랐을 때. `<...>`는 실제 경로로 바꾸고, `Copy-Item` 줄은 장 수만큼 번호를 바꿔 되풀이한다.

```powershell
cd C:\Users\user\Documents\subtitle-tc-generator
git pull origin master
Copy-Item "<SE 캡처 1 경로>" docs\screenshots\tc-error\01.png
Copy-Item "<생성기 메인 화면 경로>" docs\screenshots\generator\01_main.png
python tests\run_tests.py
git add docs\screenshots; git commit -m "docs: 발표용 스크린샷(TC 오차·생성기 화면)을 채운다"; git push origin master
```

커밋 때 pre-commit(시험 1,243건 + `tools/docs_check.py`)이 자동으로 돈다.
