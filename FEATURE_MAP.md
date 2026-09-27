# FEATURE_MAP

> **이 맵을 믿는 범위 (2026-09-25 공통 섹션·기능별 줄 전부 재검토)**
> - `파일`·`선택자`는 체커(`my-skills/.claude/skills/feature-map/scripts/check_feature_map.py`)가 코드와 대조한다. 단 `(미확인)`이 붙은 줄은 건너뛰고, `::심볼`은 그 파일에 글자가 들어 있는지만 본다.
> - `사용자 경로`·`검증`의 문장은 체커가 못 본다. 이번 재검토에서 소스와 대조해 고쳤지만, 앱을 띄워 확인한 것은 아니다.
> - 데스크톱 GUI의 `검증`은 전부 코드에서 뽑은 기대값이라 `(미확인)`이다. 웹은 1차 작성 때 관찰한 값만 그렇게 표시했다.
> - 그 문장대로 동작하지 않으면 버그라고 단정하기 전에 코드부터 확인한다.
> - 2026-09-27에 웹 페이지만 포트 8795로 띄워, 이미 있던 세션(`.work/agent-session/`)을 `?file_id=`로 다시 열어 확인했다 (무료, 에이전트 턴 없음). 확인한 문장에는 `(2026-09-27 실행 확인)`을 붙였다.
>   - `검사 시작`·`자동 교정 적용`·카드 답변은 유료 턴이라 누르지 않았다. 없는 세션 열기는 빈 폴더를 남겨서 하지 않았다. 데스크톱 GUI는 여전히 조작하지 못했다.

이 저장소에는 UI가 둘 있다. 둘 다 `checker/`(규정 검사·교정·생성 엔진)를 불러 쓴다.

- 데스크톱 GUI: `app/`, PySide6(Qt). 영상·파형·자막 표를 한 창에 두고 단계 버튼·메뉴·단축키로 작업한다.
- 웹 에이전트 페이지: `agent/static/index.html` + `agent/api.py`. srt를 올리면 Claude Agent SDK 에이전트가 검사·교정한다.

범위 밖: 엔진 CLI(`python -m checker ...`), `tools/*.bat` 실행기 (README.md 참고).

스캔하지 않은 폴더: `corpus/`, `학습한 TC 및 자막 모음/` (저작권 있는 학습 자료, 훑지 않음).

---

## 실행 방법

#### 데스크톱 GUI

```
python -m app                        # 개발용 (PySide6, libmpv 필요)
dist/자막생성기/자막생성기.exe          # 빌드본
```

- 진입점: `app/__main__.py` → `app/main.py::main`.
- 창 제목: `자막 및 TC 생성기`.
- 사용자 자료 폴더: `%APPDATA%\자막생성기` (옛 이름 `자막편집기` 폴더가 있으면 그것). `SUBTITLE_EDITOR_HOME`이 있으면 그 폴더를 쓴다. 단축키·설정·로그·발주처 기준이 여기 쌓인다.
- 발주처 기준 폴더는 `SUBTITLE_EDITOR_PROFILES`가 있으면 그 폴더다. 창 크기·위치와 분할 비율은 이 폴더가 아니라 Qt 설정(Windows 레지스트리)에 남는다.
- 테스트 데이터: `examples/ko-sdh-sample.srt`, `examples/profiles/`.
- 환경변수(이름만): `SUBTITLE_EDITOR_HOME`, `APPDATA`, `KSC_PATH`, `WHISPER_MODEL`, `FASTER_WHISPER_MODEL`, `VAD_MODEL`, `OLLAMA_HOST`, `HF_TOKEN`, `HUGGINGFACE_TOKEN`, `PYANNOTE_MODEL_DIR`, `OCR_PYTHON`, `DIARIZE_PYTHON`, `FFMPEG_DIR`, `FFMPEG_PATH`, `FFPROBE_PATH`, `SUBTITLE_EDITOR_PROFILES`, `WSL_USER`, `USER`.
- 환경변수가 없어도 창은 뜬다. 그 기능만 안 된다. `진단...`에는 기록·규정·libmpv·ffmpeg·whisper·VAD·번역·교정기 줄만 있고 OCR·화자 분리 줄은 없다.

#### 웹 에이전트 페이지

```
pip install -r requirements-agent.txt
python -m uvicorn agent.api:app --port <빈 포트>     # 저장소 루트에서 실행
```

- 저장소 루트에서 실행한다. 세션 폴더 경로(`agent/state.py::SESSIONS_ROOT`)가 현재 폴더 기준 상대 경로다.
- 기본 문서 포트는 8765이고 `.claude/launch.json`의 `mq4-agent`도 8765다. 사용자가 이미 쓰고 있을 수 있으니 다른 포트를 쓴다.
- 접속: `http://127.0.0.1:<포트>`.
- 인증: API 키를 넣지 않는다. 로컬 `claude` CLI 로그인 상태를 SDK가 쓴다. SDK는 자기에게 딸린 CLI가 있으면 그것을 쓰고, 없으면 PATH의 `claude`(Windows는 네이티브 `claude.exe`만, npm의 `claude.cmd`는 거부)나 `~/.local/bin/claude.exe`를 찾는다.
- 환경변수: `agent/`는 직접 읽지 않는다. 다만 발주처 기준을 찾는 `checker/profile.py`가 `SUBTITLE_EDITOR_PROFILES`·`SUBTITLE_EDITOR_HOME`·`APPDATA`를 읽는다.
- 테스트 데이터: `examples/ko-sdh-sample.srt`.
- 세션 산출물: `.work/agent-session/<file_id>/` (`.gitignore` 대상).

---

## 시작 전제조건

#### 데스크톱 GUI

- **이 환경의 도구로는 GUI를 조작할 수 없다.** Qt 네이티브 창이라 브라우저·CDP 도구로 열 수 없다. 아래 GUI 기능은 모두 사람이 직접 하거나 수동으로 표시한다.
- 1차 작성 때도 GUI는 한 번도 실행하지 않았다. GUI `검증`은 전부 코드에서 뽑은 기대값이다.
- 시작 상태: 창을 막 띄운 직후. 상태줄에 `영상과 자막을 여세요`, 열린 모달 없음, `검사 결과`·`진행 기록` 독은 숨김.
- 번역 서버(Ollama)가 안 떠 있으면 창이 뜬 직후 앱이 Ollama를 띄우려 한다. 이때 상태줄 문구가 `번역 서버(Ollama)를 띄웠습니다: …`나 `Ollama를 찾지 못해 …`로 바뀐다. 띄운 Ollama는 창을 닫아도 남는다.
- 지난번 창 크기·위치와 분할 비율이 되살아난다 (`app/window.py::_restore_layout`). 독 배치는 되살리지 않는다. 배치 검증은 시작 배치가 사람마다 다를 수 있다.
- 단계 버튼은 상태에 따라 꺼진다.
  - 영상이 없으면 `자막 만들기`만 꺼진다.
  - 자막이 없으면 나머지 단계가 꺼진다.
  - 꺼진 이유는 버튼 툴팁에 나온다.
- 도구가 닿지 않는 경로:
  - OS 파일 선택 대화상자 (영상·자막·대본 열기, 자막 저장)
  - 메뉴바와 툴바 (네이티브 위젯)
  - libmpv 영상 재생 (없으면 영상을 열 때 경고 팝업이 뜨고 영상이 안 열린다. 재생 단추는 말없이 아무 일도 안 한다)
  - 로컬 번역 서버(Ollama), whisper 전사, 한국어 교정기(`KSC_PATH`), OCR: 설치돼 있어야 하고 오래 걸린다.
- 시험용 자막: `examples/ko-sdh-sample.srt`. 영상은 이 저장소에 없다 (`git ls-files`에 영상 파일 0개).

#### 웹 에이전트 페이지

- **세션을 만들면 유료 호출이 나간다.** `검사 시작`, `자동 교정 적용`, 확인 카드 답변 제출 모두 Claude Agent SDK 에이전트 턴을 돌린다. 턴 하나의 예산 상한은 0.50 USD(`agent/loop.py::MAX_BUDGET_USD_PER_CALL`)다.
- 서버가 떠 있어야 한다. 서버 확인은 `GET /` 가 200이면 된다. 이 요청은 에이전트를 돌리지 않는다.
- 시작 화면: 주소에 `?file_id=`가 없으면 업로드 폼(`#upload-form`)만 보이고 세션 영역(`#session-view`)은 숨김. 있으면 바로 세션 영역이 열린다.
- 로그인 화면은 없다. 페이지 자체에는 인증이 없다.
- 발주처는 넷플릭스·디즈니+·쿠팡플레이, 종류는 SDH·번역, 언어는 한국어뿐이다.
- 이 세 발주처의 규정 파일은 `rules/private/`(`.gitignore` 대상)에만 있다. 없으면 검사가 프로파일 오류로 실패한다. GUI에서는 사용자 기준도 없으면 `플랫폼`에 `(규정 파일을 찾지 못했습니다)`가 나온다.
- 도구가 닿지 않는 경로: 클릭·입력만으로는 srt 파일을 고를 수 없다. 파일 올리기 도구가 필요하다. 결과 srt·북마크 내려받기는 파일 다운로드라 사용자 허락이 필요하다. 에이전트 응답 내용은 매번 다를 수 있다.

---

## 조작 관례

#### 공통

- **격리**: 사용자가 이미 띄운 서버·창에 붙지 않는다. 자기 포트로 따로 띄우고, 띄우기 전에 포트가 비었는지 확인한다.
- **정리**: 자기가 띄운 프로세스의 PID만 종료한다. 이름으로 일괄 종료하지 않는다.
- **건드리지 않기**: 관련 없는 설정·데이터를 바꾸지 않는다. 테스트로 남긴 산출물은 보고에 적는다.

#### 데스크톱 GUI

- Qt에는 `objectName`이 거의 없다. 유일한 것은 작업 단계 독의 `stages`다. 위젯은 보이는 문구로 찾는다.
- 툴바·메뉴 문구는 코드 문자열 그대로다. `▶ ‖`처럼 공백이 들어간 문구는 공백까지 맞춘다.
- 위젯이 없고 단축키만 있는 기능은 `선택자: 없음 — 단축키 전용`으로 적었다.
- 단축키는 사용자가 바꿀 수 있다. 맵의 키는 기본값이고, 실제 값은 `<사용자 자료 폴더>\shortcuts.json`에 남은 변경분(기본값과 다른 키만)과 합쳐진다.
- 오래 걸리는 단계(자막 만들기, 번역, 감수, 윤문)는 고정 시간 대기 대신 상태줄 문구와 `진행 기록` 독의 끝 문구를 본다.
- `python -m app --selftest`는 창 없이 진단만 하고, 결과를 **실행 파일 옆** `진단.txt`에 쓴다. 표준 출력에도 찍고, 사용자 자료 폴더 `log.txt`에도 줄을 남긴다. 개발 환경에서는 그 옆이 파이썬 설치 폴더라서 에이전트가 돌리지 않는다.

#### 웹 에이전트 페이지

- **세션을 함부로 만들지 않는다.** `검사 시작`은 유료 에이전트 턴을 돌린다. 이미 만들어진 `?file_id=<id>` 세션을 다시 읽는 것은 무료다.
- 새 세션이 꼭 필요할 때만 만든다. 한 검증에 한 세션을 쓰고, 세션 id를 보고에 적는다.
- `자동 교정 적용`과 카드 답변은 각각 추가 유료 턴이다. 맵의 검증 항목에 필요할 때만 누른다.
- 준비 확인: 존재하지 않는 세션 id를 GET하면 404가 나온다 (무료). 다만 그때마다 빈 세션 폴더가 `.work/agent-session/` 아래 생긴다 (`agent/state.py::load`가 폴더를 먼저 만든다).
- 대기: 고정 시간 sleep은 쓰지 않고 끝 상태를 폴링한다. 페이지는 상태가 `running`일 때만 1초마다 스스로 다시 읽는다. 첫 `검사 시작`은 첫 에이전트 턴이 끝날 때까지 응답이 없고, 그동안 폴링도 없다. 단, 자동 교정 승인을 기다리는 동안에도 `#status-text`는 `running`으로 보인다. `#status-text`만 보고 기다리면 끝나지 않으니, `#fix-approval`이 보이는지도 함께 확인한다.
- 읽기 전용 평가: 페이지에서 JS를 돌릴 때는 DOM 텍스트를 읽는 데만 쓴다. `fetch`로 API를 직접 호출해 세션을 만들지 않는다.
- 콘솔: 검증 기대값에 "에러 없음"이 있으면 콘솔을 켜 둔다.
- `alert()`가 뜨는 경우가 있다 (업로드 실패, 세션 없음, 세션 오류). 뜨면 문구를 보고에 적고 닫는다.
- 페이지는 공개 가능한 자막만 받으라고 경고한다. 실제 납품 파일은 올리지 않는다.

---

## 증거와 건너뜀 보고

검증을 보고할 때 이 형식을 쓴다.

```markdown
- 대상: <기능 / 변경>
- 전제조건: 시작 전제조건 충족 여부 (다르면 무엇이 달랐는지)
- 한 것: <실행한 명령·조작 순서>
- 관찰: <본 것을 그대로 — 문구, 개수, 응답 코드, 로그 한 줄>
- 버그 수정이면: 수정 전 커밋에서 재현됨 / 수정 후 사라짐
- 증거 파일: <스크린샷·녹화·로그 경로> (없으면 "없음")
- 건너뜀: <맵에 있는 변형 중 못 한 것과 이유> (없으면 "없음")
```

- 맵에 나열된 변형(메뉴 경로, 단축키 경로 등) 가운데 하나라도 빠졌으면 증거는 불완전하다. 빠진 것은 "건너뜀"에 적는다.
- "관찰"에는 본 것만 적는다. 코드에서 추론한 것은 "추론:"으로 따로 적는다.
- 데스크톱 GUI는 이 환경에서 조작할 수 없으므로, GUI 항목은 "건너뜀: GUI 조작 불가 (수동)"으로 적는다.

---

## 기능

두 UI는 서로 다른 화면이다. 기능 이름 앞의 `GUI`와 `웹`으로 구분한다.

#### 부분 1. 데스크톱 GUI (`app/`)

### GUI 영상 열기
- 사용자 경로: 메뉴 `파일(&F)` → `영상 열기...` → 파일 선택 대화상자
- 단축키: Ctrl+O
- 선택자: `파일(&F)`, `영상 열기...`
- 파일: `app/window.py::_build_menu`, `app/window.py::open_video`, `app/player.py::Player`
- 검증: (미확인) 영상을 고르면 상태줄에 `영상: <파일명>  <fps>fps — 파형을 만드는 중입니다...`가 뜬다. `자막 만들기` 버튼이 켜진다. libmpv가 없으면 `영상을 재생할 수 없습니다` 경고 팝업이 뜨고, 영상은 열리지 않으며 `자막 만들기`도 꺼진 채다.

### GUI 자막 열기
- 사용자 경로: 메뉴 `파일(&F)` → `자막 열기...` → 파일 선택 대화상자
- 단축키: Ctrl+Shift+O
- 선택자: `자막 열기...`
- 파일: `app/window.py::_build_menu`, `app/window.py::open_subtitle`, `app/model.py::SubtitleModel`
- 검증: (미확인) `examples/ko-sdh-sample.srt`를 열면 자막 표에 행이 채워지고 상태줄에 `자막 <개수>개: ko-sdh-sample.srt`가 뜬다. 자막이 필요한 단계 버튼이 켜진다. 읽지 못한 파일이면 `자막을 읽지 못했습니다` 경고가 뜬다.

### GUI 원어 대본 열기
- 사용자 경로: 메뉴 `파일(&F)` → `원어 대본 열기...` → 워드·텍스트·PDF 선택
- 단축키: Ctrl+Alt+O
- 선택자: `원어 대본 열기...`
- 파일: `app/window.py::_build_menu`, `app/window.py::open_script`
- 검증: (미확인) 자막이 열려 있으면 상태줄에 `대본 <n>줄을 원어 칸에 넣었습니다`가 뜬다(`진행 기록` 독은 작업을 돌리기 전에는 숨어 있다). 자막 수와 줄 수가 다르면 `자막은 <m>개입니다. 수가 달라 뒤로 갈수록 어긋납니다`가 덧붙는다. 자막이 없으면 `대본 <n>줄을 읽었습니다. 영상을 열고 [영상에서 자막 만들기]를 누르면 대조합니다`가 뜬다.

### GUI 자막 저장
- 사용자 경로: 메뉴 `파일(&F)` → `자막 저장` → 저장 대화상자
- 단축키: Ctrl+S
- 선택자: `자막 저장`
- 파일: `app/window.py::_build_menu`, `app/window.py::save_subtitle`, `checker/writers.py::write_srt`
- 검증: (미확인) 저장 대화상자의 제안 이름이 `<원본>.edited.srt` 꼴이다(`.edited`는 설정 `save_suffix` 기본값, 자막 파일을 연 적이 없으면 `자막.srt`). 고르면 상태줄에 `저장했습니다: <경로>`가 뜨고 새 파일이 생기며, 원본 파일은 그대로다. 원어 칸이 차 있으면 `<이름>.원어.srt`도 생기고 문구 끝에 `  /  원어: <파일명>`이 붙는다. 자막이 없으면 아무 일도 없다.

### GUI 화면 배치 전환
- 사용자 경로: 메뉴 `보기(&V)` → 배치 이름
- 단축키: Ctrl+1(타임코드 작업), Ctrl+2(번역 작업), Ctrl+3(영상 크게), Ctrl+0(고르게)
- 선택자: `보기(&V)`, `타임코드 작업 (파형 크게)`, `번역 작업 (표 크게)`, `영상 크게`, `고르게`
- 파일: `app/window.py::_build_menu`, `app/window.py::apply_layout`
- 검증: (미확인) 고르면 영상·표·파형의 면적이 바뀌고 상태줄에 `배치: spotting` 등이 뜬다(`진행 기록` 독은 숨어 있으면 안 보인다). 창을 닫았다 다시 열면 마지막 분할 비율이 되살아난다.

### GUI 툴바 작업 설정
- 사용자 경로: 창 위쪽 툴바 → `플랫폼`·`종류`·`원어` 드롭다운, 체크박스 두 개
- 선택자: `플랫폼`, `종류`, `원어`, `만들 때 번역까지`, `화면 캡션도 OCR로 읽기`
- 파일: `app/window.py::_build_pipeline`, `app/window.py::_reload_platforms`
- 검증: (미확인) `종류`에 `translation`·`sdh`, `원어`에 `en`·`ko`·`auto`가 나온다. `플랫폼` 목록 끝에 `＋ 새 기준 만들기...`가 있다. 규정 파일을 못 찾으면 `(규정 파일을 찾지 못했습니다)`가 나온다.

### GUI 작업 기준 창 (발주처 기준·단축키·설정)
- 사용자 경로: 툴바 `작업 기준...`, 또는 `플랫폼` 드롭다운에서 `＋ 새 기준 만들기...` 선택 → `작업 기준` 창
- 선택자: `작업 기준...`, `＋ 새 기준 만들기...`, `발주처 이름`, `기본값으로 되돌리기`
- 파일: `app/window.py::open_settings`, `app/settings.py::SettingsDialog`, `app/settings.py::_save`
- 검증: (미확인) 창 왼쪽에 여섯 탭이 있다. 첫 줄 문구가 `작업 기준`, `이 작업에서`, `검사 규칙`, `단축키와`, `저장·파형`, `적용 중인`이다. `발주처 이름`을 비우고 저장하면 `단축키와 설정을 저장했습니다.` 팝업이 뜨고 프로파일은 만들지 않는다. 이름을 적고 저장하면 `저장했습니다` 팝업에 경로가 나오고, `플랫폼` 목록에 그 이름이 추가된다.

### GUI 자막 만들기
- 사용자 경로: `작업 단계` 독 → `소재` 줄 → `자막 만들기` 버튼, 또는 메뉴 `단계(&S)` → `자막 만들기`
- 선택자: `자막 만들기`, `단계(&S)`, `작업 단계`, `stages`
- 파일: `checker/pipeline.py::STAGES`, `checker/generate.py::generate`, `app/window.py::run_generate`, `app/jobs.py::GenerateJob`
- 검증: (미확인) 영상이 없으면 버튼이 꺼지고 툴팁이 `영상이 필요합니다`로 시작한다. `종류`가 `translation`이면 원어 대본을 고르는 파일 창이 먼저 뜨고, 취소하면 대본 없이 진행한다. 진행 중에는 상태줄 막대와 `<분>:<초> 경과`가 보이고, 끝나면 상태줄에 `자막 <개수>개를 만들었습니다`가 뜬다.

### GUI ① 1차 번역
- 사용자 경로: `작업 단계` 독 → `번역` 줄 → `① 1차 번역`, 또는 메뉴 `단계(&S)`
- 선택자: `① 1차 번역`
- 파일: `checker/pipeline.py::stage_translate`, `app/window.py::run_translate`, `app/jobs.py::TranslateJob`
- 검증: (미확인) 자막이 없으면 버튼이 꺼진다. 끝나면 상태줄에 `1차 번역했습니다 — 타임코드는 그대로입니다(<개수>개)`가 뜬다. `번역` 줄 아래 회색 글에 `다음은 [② 번역 감수]`가 나온다.

### GUI ② 번역 감수
- 사용자 경로: `작업 단계` 독 → `번역` 줄 → `회차` 드롭다운(1~5) 선택 → `② 번역 감수`
- 선택자: `② 번역 감수`, `회차`
- 파일: `checker/pipeline.py::stage_revise`, `app/window.py::run_revise`, `app/jobs.py::ReviseJob`
- 검증: (미확인) `회차` 기본값은 2다. 끝나면 상태줄에 `② 번역 감수 — <n>곳 고쳤습니다`가 뜬다. 고친 곳이 있으면 이 문구는 곧 마지막 수정 줄로 덮이고, 바뀐 자막 줄이 `진행 기록`에 `#<번호> ... -> ...` 꼴로 최대 12줄 나온다(넘으면 `… 외 <k>곳`). 원어가 없으면 `원어가 없어 오역 대조 없이 돕니다`가 나온다.

### GUI ③ 자막 윤문·QA
- 사용자 경로: `작업 단계` 독 → `번역` 줄 → `③ 자막 윤문·QA`
- 선택자: `③ 자막 윤문·QA`
- 파일: `checker/pipeline.py::stage_polish`, `app/window.py::run_polish`, `app/jobs.py::PolishJob`
- 검증: (미확인) 끝나면 상태줄에 `③ 자막 윤문·QA 완료 — 남은 지적 <n>건`이 뜬다. 지적이 있으면 `검사 결과` 독이 열린다.

### GUI ② 한국어 교정
- 사용자 경로: `작업 단계` 독 → `한국어` 줄 → `② 한국어 교정`
- 선택자: `② 한국어 교정`
- 파일: `checker/pipeline.py::stage_korean`, `checker/pipeline.py::correct_and_check`, `app/window.py::run_korean`, `app/jobs.py::CheckJob`
- 검증: (미확인) 교정기를 못 찾으면 `한국어 교정기를 찾지 못했습니다` 팝업이 뜨고 작업은 시작하지 않는다. 찾으면 끝에 상태줄에 `② 한국어 교정 완료 — 남은 지적 <n>건`이 뜬다. n은 한국어 지적과 규정 지적을 합친 수다. 교정기를 찾았는데 올리지 못하면 `진행 기록`에 `한국어 교정 레인 건너뜀: …`이 남는다.

### GUI ③ 자막 QA
- 사용자 경로: `작업 단계` 독 → `한국어` 줄 → `③ 자막 QA`
- 선택자: `③ 자막 QA`
- 파일: `checker/pipeline.py::stage_check`, `checker/pipeline.py::correct_and_check`, `checker/pipeline.py::stage_fixes`, `app/window.py::run_check`, `app/jobs.py::CheckJob`
- 검증: (미확인) 끝나면 상태줄에 `③ 자막 QA 완료 — 남은 지적 <n>건`이 뜬다. n이 0보다 크면 `검사 결과` 독이 열리고 n행이 채워진다. 0이면 독이 숨는다.

### GUI 용어표
- 사용자 경로: `작업 단계` 독 → `조사` 줄 → `용어표`
- 선택자: `용어표`
- 파일: `checker/pipeline.py::stage_terms`, `app/window.py::run_terms`, `app/jobs.py::TermsJob`
- 검증: (미확인) 끝나면 상태줄에 `용어 <n>개 중 <k>개에 표기를 채웠습니다: <파일>.terms.tsv`가 뜬다. 뽑힌 용어가 `검사 결과` 독에 행으로 나온다. 웹 조사가 함께 돌아 네트워크가 필요하다.

### GUI 캐릭터 문서
- 사용자 경로: `작업 단계` 독 → `조사` 줄 → `캐릭터 문서`
- 선택자: `캐릭터 문서`
- 파일: `checker/pipeline.py::stage_characters`, `app/window.py::run_characters`, `app/jobs.py::CharactersJob`
- 검증: (미확인) 끝나면 상태줄에 `인물 <n>명 — 표 <파일>.characters.tsv, 문서 <파일>.characters.md`가 뜨고 `조사` 줄 아래 회색 글에 인물 수 요약이 나온다.

### GUI 검사 결과 목록
- 사용자 경로: 지적이 생기면 아래쪽에 `검사 결과` 독이 열린다 → 행을 더블클릭
- 선택자: `검사 결과`, `자막`, `규칙`, `내용`
- 파일: `app/window.py::_build_results`, `app/window.py::_show_violations`, `app/window.py::_jump_to_violation`
- 검증: (미확인) 열 제목은 `자막`·`규칙`·`내용`이다. `규칙` 칸에 `<규칙ID> 자동` 또는 `<규칙ID> 확인`이 붙는다. 행을 더블클릭하면 그 번호의 자막 행이 선택되고, 영상이 열려 있으면 영상이 그 시작 지점으로 간다. 용어표 결과 행(번호 0)은 더블클릭해도 자막으로 이동하지 않는다. 지적이 0건이면 독이 숨는다.

### GUI 자막 표 더블클릭 이동
- 사용자 경로: 자막 표에서 행을 더블클릭
- 선택자: 없음 — 자막 표 행 (표시 문구가 없는 표)
- 파일: `app/window.py::_jump_to_row`, `app/model.py::SubtitleModel`
- 검증: (미확인) 영상이 그 자막의 시작 위치로 이동하고 위치 표시가 바뀐다. `자막` 칸을 더블클릭하면 그 칸 편집도 열린다. 영상이 안 열려 있으면 이동은 없고, `자막` 칸이면 편집만 열린다.

### GUI 재생 컨트롤
- 사용자 경로: 영상 아래 단추 `◀|`, `▶ ‖`, `|▶`
- 단축키: Esc 또는 Space(재생/일시정지), Ctrl+Shift+Left(1프레임 뒤), Ctrl+Shift+Right(1프레임 앞)
- 선택자: `◀|`, `▶ ‖`, `|▶`
- 파일: `app/shortcuts.py::ACTIONS`, `app/window.py::toggle_play`, `app/window.py::step`, `app/window.py::keyPressEvent`
- 검증: (미확인) 재생 중에는 영상 옆 `00:00:00,000 / 00:00:00,000` 꼴 위치 표시가 계속 올라가고, 재생 위치가 자막 구간 안에 있을 때만 자막 표 선택이 따라간다(자막 사이 빈 구간에서는 선택이 그대로다). 일시정지하면 표시가 멈춘다. 영상이 없으면 단추가 아무 일도 하지 않는다.

### GUI 자막 목록 이동
- 사용자 경로: 자막 표에서 단축키, 또는 Ctrl+G로 번호 입력 창
- 단축키: PgUp(이전 자막), PgDown(다음 자막), Ctrl+G(번호로 이동)
- 선택자: `자막 번호로 이동`
- 파일: `app/shortcuts.py::ACTIONS`, `app/window.py::go_previous`, `app/window.py::go_next`, `app/window.py::go_to_number`
- 검증: (미확인) PgDown을 누르면 다음 행이 선택되고, 영상이 열려 있으면 영상이 그 자막 시작으로 간다. 마지막 행에서는 그대로다. Ctrl+G 창의 입력란에 번호를 넣고 확인하면 그 번호의 행이 선택된다. 이전/다음 이동에는 전용 버튼이 없다.

### GUI 자막 편집 (나누기·합치기·하이픈·줄바꿈)
- 사용자 경로: 자막 표에서 행을 고른 뒤 단축키
- 단축키: Ctrl+Space(재생 위치에서 나누기), Alt+Space(다음과 합치기), Alt+Shift+Space(대화로 합치기), Ctrl+-(하이픈 넣고 빼기), Ctrl+\(줄바꿈 제거)
- 선택자: 없음 — 단축키 전용
- 파일: `app/shortcuts.py::ACTIONS`, `app/window.py::split_cue`, `app/window.py::merge_cue`, `app/window.py::merge_dialogue`, `app/window.py::toggle_dash`, `app/window.py::remove_breaks`, `app/window.py::_merge`, `app/edits.py::split_at`, `app/edits.py::merge_with_next`, `app/edits.py::toggle_dash`, `app/edits.py::remove_line_breaks`
- 검증: (미확인) 나누기·합치기 뒤 상태줄에 `#<번호>를 나눴습니다` 또는 `#<번호>를 다음 자막과 합쳤습니다`가 뜨고(`진행 기록`은 독이 열려 있을 때만 보인다) 표 행 수가 하나 늘거나 준다. 대화로 합치면 `(대화)`가 덧붙는다. 나누기는 영상이 열려 있어야 한다. 재생 위치가 자막 시작·끝에서 0.1초 안이면 나누지 않고, 마지막 자막은 합칠 수 없다. 이때도 성공 문구는 그대로 뜨고 행 수만 안 바뀐다.

### GUI 자막 위치 (화면 위·아래)
- 사용자 경로: 자막 표에서 행을 고른 뒤 단축키
- 단축키: Alt+Up(위로), Alt+Down(아래로)
- 선택자: 없음 — 단축키 전용
- 파일: `app/shortcuts.py::ACTIONS`, `app/window.py::place_top`, `app/window.py::place_bottom`, `app/edits.py::set_position`
- 검증: (미확인) Alt+Up 뒤 선택한 자막 글자 앞에 `{\an8}`가 붙고, Alt+Down 뒤에는 그 태그가 없다.

### GUI 인점·아웃점
- 사용자 경로: 자막 표에서 행을 고르고 재생 위치를 맞춘 뒤 단축키
- 단축키: F5(인점), F6(아웃점)
- 선택자: 없음 — 단축키 전용
- 파일: `app/shortcuts.py::ACTIONS`, `app/window.py::set_in_point`, `app/window.py::set_out_point`, `app/edits.py::set_in_point`, `app/edits.py::set_out_point`
- 검증: (미확인) 성공하면 상태줄과 `진행 기록`에 `#<번호> 인점을 <타임코드>로`(아웃점이면 `아웃점을`)가 남고 표의 시간이 바뀐다. 이웃 자막을 침범하거나 뒤집히면 `이웃 자막을 침범하거나 자막이 뒤집혀서 하지 않았습니다`가 뜨고 시간은 그대로다. 영상이 안 열려 있으면 아무 일도 없다.

### GUI 파형 확대·축소
- 사용자 경로: 영상 아래 `＋`·`－` 단추, 또는 파형 위에서 Ctrl+휠
- 단축키: Alt+=(확대), Alt+-(축소)
- 선택자: `＋`, `－`
- 파일: `app/shortcuts.py::ACTIONS`, `app/window.py::zoom_in`, `app/window.py::zoom_out`, `app/waveform.py::Waveform`
- 검증: (미확인) `＋`을 누르면 파형의 같은 화면 폭에 보이는 시간 길이가 줄어 자막 구간이 넓게 보이고, `－`을 누르면 늘어난다. 휠만 돌리면 파형이 좌우로 이동하고, 그 뒤로는 파형이 재생 위치를 따라가지 않는다(`작업 기준` 창을 닫으면 설정값으로 돌아온다).

### GUI 파형에서 위치 이동·자막 경계 끌기
- 사용자 경로: 파형 어디든 클릭하면 그 시간으로 이동. 아래쪽 60px 자막 띠에서 자막 시작·끝 가장자리에 마우스를 대면 좌우 화살표 커서가 되고 끌어서 옮긴다. 끌 때 이웃 자막과 겹치는 것은 막지 않는다.
- 선택자: 없음 — 파형 위젯은 표시 문구가 없다
- 파일: `app/waveform.py::Waveform`, `app/window.py::_seek_to`, `app/window.py::_cue_changed`
- 검증: (미확인) 파형을 클릭하면 재생 위치 선이 그 시점으로 옮겨진다. 영상 위치와 시간 표시는 영상이 열려 있을 때만 바뀐다. 가장자리를 끌었다 놓으면 자막 표의 해당 행 시간이 바뀐다.

### GUI 진행 표시
- 사용자 경로: 단계 버튼을 누르면 상태줄에 움직이는 막대와 경과 시간이 나타나고 아래쪽에 `진행 기록` 독이 열린다.
- 선택자: `진행 기록`
- 파일: `app/window.py::_build_progress`, `app/window.py::_busy`, `app/window.py::_note`, `app/window.py::_tick`, `app/window.py::_start`
- 검증: (미확인) 작업 중에는 단계 버튼이 모두 꺼지고 상태줄에 `<분>:<초> 경과`가 올라간다. 끝나면 `<분>:<초> 걸림`으로 바뀌고 버튼이 다시 켜진다. 실패하면 `작업을 마치지 못했습니다` 경고가 뜬다.

### GUI 단축키 확인·변경
- 사용자 경로: 메뉴 `도움말(&H)` → `단축키...` 팝업에서 확인. 변경은 `작업 기준` 창에서 두 줄 이름(`단축키와`/`기능`) 탭을 열고 키 칸을 눌러 새 조합을 입력한 뒤, 창 아래 저장 버튼을 누른다.
- 단축키: F1
- 선택자: `도움말(&H)`, `단축키...`, `기능과 단축키`, `기본값으로 되돌리기`
- 파일: `app/window.py::_build_menu`, `app/window.py::show_shortcuts`, `app/settings.py::_shortcut_tab`, `app/settings.py::_save_shortcuts`, `app/window.py::reload_shortcuts`, `app/shortcuts.py::save`
- 검증: (미확인) 팝업 제목이 `기능과 단축키`이고 `[재생]`·`[이동]`·`[편집]`·`[위치]`·`[타임코드]`·`[파형]` 여섯 묶음과 키·설명이 나열된다. 탭에서 같은 키를 두 기능에 주고 저장하면 `단축키가 겹칩니다` 확인창이 뜬다. 바꾼 키는 `<사용자 자료 폴더>\shortcuts.json`에 기본값과 다른 키만 남고, 창을 닫으면 재시작 없이 적용된다.

### GUI 진단
- 사용자 경로: 메뉴 `도움말(&H)` → `진단...`
- 선택자: `진단...`, `진단`
- 파일: `app/window.py::show_diagnosis`, `app/diagnose.py::collect`, `app/diagnose.py::as_text`
- 검증: (미확인) 제목이 `진단`인 창에 `[OK  ]` 또는 `[없음]` 표시와 항목 이름(`기록(log)`, `규정 파일`, `영상 재생(libmpv)`, `ffmpeg`, `전사(whisper 필터)` 등)이 줄로 나온다. 끝줄은 `모두 갖춰졌습니다.` 또는 `없는 것: …`이다. 못 찾은 항목 가운데 libmpv·ffmpeg·교정기·번역 모델 없음에는 설치 안내가, whisper·VAD 등에는 오류 첫 줄이 붙는다.

#### 부분 2. 웹 에이전트 페이지 (`agent/static/index.html`)

### 웹 srt 업로드·검사 시작
- 사용자 경로: 첫 화면 → srt 파일 선택 → `발주처`·`종류`·`언어` 선택 → `검사 시작` 버튼 (유료 에이전트 턴이 돈다)
- 선택자: `#f`, `input[name="file"]`, `select[name="platform"]`, `select[name="kind"]`, `select[name="language"]`, `button[type="submit"]`, `검사 시작`
- 파일: `agent/static/index.html`, `agent/api.py::create_session`
- 검증: 제출해도 첫 에이전트 턴이 끝날 때까지 폼이 그대로 있고 진행 표시가 없다. 버튼도 안 꺼져서 다시 누르면 유료 세션이 하나 더 생긴다. 턴이 끝나면 업로드 폼이 숨고 `#session-view`가 나타나며 주소가 `?file_id=f_<16진수 12자리>`로 바뀐다. `.srt`가 아닌 파일이면 `업로드 실패:` alert가 뜬다. 1차 작성 때 관찰(재확인 안 함): `examples/ko-sdh-sample.srt` + netflix/sdh/ko로 `POST /api/sessions`가 201과 `{"file_id": "f_9c9e3e9223a2", "status": "running"}`을 돌려줬다.

### 웹 진행 상태·로그
- 사용자 경로: 검사 시작 뒤 화면 위쪽 `상태:` 줄과 아래쪽 로그 영역
- 선택자: `#status-text`, `#loop-count`, `#log`
- 파일: `agent/static/index.html::render`, `agent/api.py::get_session`
- 검증: `#status-text`가 `running`, `waiting_for_user`, `done`, `error` 중 하나로 채워지고 `#loop-count`에 숫자가 있다. `#log`에 `[<회차>] <도구>: <요약>` 줄이 쌓인다. 상태가 `running`인 동안 페이지가 1초마다 스스로 다시 읽는다. 1차 작성 때 관찰(재확인 안 함): 화면 텍스트에 `상태: running (회차 1)`과 `agent_note`·`run_check`·`permission`·`turn_result` 로그 줄이 나왔다. (2026-09-27 실행 확인: `done`·`waiting_for_user`·`running` 세션에서 봤다. `running`인 동안 3초에 3번 다시 읽었다)

### 웹 자동 교정 승인
- 사용자 경로: `자동 교정 가능한 위반이 있습니다. 적용할까요?` 카드 → `자동 교정 적용` 버튼 (추가 유료 턴)
- 선택자: `#fix-approval`, `#approve-fix-btn`, `자동 교정 적용`
- 파일: `agent/static/index.html::render`, `agent/static/index.html::approve-fix-btn`, `agent/api.py::approve_fix`
- 검증: 승인 대기 상태에서만 `#fix-approval`이 보인다. `#status-text`는 이 동안에도 `running`이다. 버튼을 누르면 서버가 유료 에이전트 턴을 끝낼 때까지 응답하지 않아서 그동안 카드가 그대로 보이고, 끝난 뒤에야 카드가 사라지며 `#log`에 줄이 더 붙는다. 그 턴에도 에이전트가 교정을 하지 않아 자동 교정 위반이 남으면 카드는 그대로 남는다. 그 사이에 다시 누르면 유료 턴이 한 번 더 돈다 (미확인: 이 단계 이후 흐름은 실행한 적 없음). 1차 작성 때 관찰(재확인 안 함): 위 샘플 세션에서 `#log`에 `permission: run_fix — 자동교정 적용 전 사람 승인 필요, 거부함`이 나오고 승인 카드가 화면에 떴다. (표시 부분만 2026-09-27 실행 확인: `자동 교정 가능한 위반이 있습니다. 적용할까요?` 카드와 `running`. 버튼은 유료라 누르지 않았다)

### 웹 확인 카드 응답
- 사용자 경로: `waiting_for_user` 상태에서 `#cards`에 카드가 나온다 → 각 카드의 `승인`·`거부`·`직접수정` 버튼 중 하나 클릭 → 모든 카드에 답하면 자동 제출 (추가 유료 턴)
- 선택자: `#cards`, `승인`, `거부`, `직접수정`, `확인함`
- 파일: `agent/static/index.html::renderCards`, `agent/api.py::answer`, `agent/api.py::get_cue_text`
- 검증: 카드마다 `<규칙ID> — <조항> (<n>번 큐)` 제목 아래 그 대사 원문이 회색 상자에 나온다. 원문을 못 가져오면 `원문을 못 불러왔습니다`가 빨간 글씨로 나온다. 카드 일부만 답하면 제출되지 않는다. 에이전트가 직접 묻는 카드는 제목이 `에이전트 질문 — <사유>`이고, 원문 상자가 없으며 버튼이 `확인함` 하나다. (미확인: 이 화면까지 간 실행 관찰 없음) (표시 부분만 2026-09-27 실행 확인: 예 `DP07 — 실무 스펙 / 자막 간격 (2번 큐)`, 카드마다 `승인`·`거부`·`직접수정`. 답변은 유료라 누르지 않았다)

### 웹 완료 화면·결과 srt 다운로드
- 사용자 경로: 처리가 끝나면 `#result` 영역에 `완료`가 나온다 → `수정된 srt 다운로드` 버튼
- 선택자: `#result`, `수정된 srt 다운로드`
- 파일: `agent/static/index.html::render`, `agent/api.py::download`, `agent/api.py::get_session`
- 검증: 상태가 `done`이면 `#result`에 `완료`, `고친 것 <n>건, 남은 것 0건, <k>회차 소요`(남은 것은 늘 0), `비용 $<x>, 소요시간 <ms>ms, 토큰 입력 <a>/출력 <b>` 줄이 보인다. 다운로드 버튼을 누르면 `<file_id>.srt` 파일이 내려온다. 상태가 `done`이 아닐 때 주소를 직접 열면 409가 나온다. (미확인: `done`까지 간 실행 관찰 없음) (2026-09-27 실행 확인: `고친 것 10건, 남은 것 0건, 3회차 소요`, `비용 $0.041, 소요시간 21402ms, 토큰 입력 8/출력 799`. 다운로드 응답은 `f_61fb9b1b744b.srt`, 완료 전 세션은 409 `not_done_yet`)

### 웹 SE 북마크 다운로드
- 사용자 경로: 완료 화면에서 영상 확인이 필요한 위반이 있으면 `영상 확인이 필요한 위반 <n>건은 SE 북마크로 내보냈습니다` 문구와 `북마크 파일 다운로드` 버튼이 나온다
- 선택자: `북마크 파일 다운로드`
- 파일: `agent/static/index.html::render`, `agent/api.py::download_bookmarks`
- 검증: 버튼을 누르면 `<작업본 srt 이름>.SE.bookmarks` 파일(내용은 JSON)이 내려온다. 북마크가 없는 세션의 주소를 직접 열면 404가 나온다. (미확인: 이 화면까지 간 실행 관찰 없음) (2026-09-27 실행 확인: `02-fixed.srt.SE.bookmarks`, `application/json`. 북마크 없는 세션은 404 `no_bookmarks`. 응답만 받고 파일은 저장하지 않았다)

### 웹 세션 이어 보기
- 사용자 경로: 주소 끝에 `?file_id=<id>`를 붙여 열면 업로드 없이 그 세션 화면으로 바로 들어간다 (무료, 에이전트를 돌리지 않는다)
- 선택자: `#session-view`
- 파일: `agent/static/index.html::fileIdFromUrl`, `agent/api.py::get_session`
- 검증: 있는 세션이면 업로드 폼이 숨고 `#status-text`에 저장된 상태가 나온다. 없는 세션이면 `세션을 찾을 수 없습니다` alert가 뜬다. 닫으면 업로드 폼은 숨은 채 빈 세션 화면이 남는다.

---

## 사용자가 닿을 수 없는 것

- `GET /api/sessions/{file_id}/result`: 화면에 링크가 없다. 주소 직접 입력으로만 닿는다.
- `agent/mcp_server.py`, `agent/eval.py`, `agent/experiment_prompt.py`: 화면이 없는 도구다. 이 맵의 대상이 아니다.
- `agent/eval.py`와 `agent/experiment_prompt.py`는 에이전트 턴을 돌려 유료 호출이 나간다. `agent/eval.py`는 서버 주소가 `127.0.0.1:8765`로 고정이다.
