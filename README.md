# 자막 및 TC 생성기 (작업 중)

전문 번역가·자막 작업자를 위한 **자막·타임코드 생성기**. 영상 하나에서 전사 → 대조 →
번역 → 재분할 → 스포팅까지 이어 붙이고, SubtitleEdit보다 **자동화 수준이 높고 정확도가
높은 것**을 목표로 한다.

한국어 교정은 이 저장소가 직접 하지 않는다. 옆 프로젝트
[korean-subtitle-corrector](https://github.com/tigermorning/korean-subtitle-corrector)를
라이브러리로 불러 쓴다 — **자막 지식은 여기가, 한국어 규범 지식은 그쪽이 갖는다**
(`checker/korean.py`).

## 왜 만드나

SubtitleEdit(MIT, 엔진 `libse`가 NuGet으로 배포됨)은 포맷 파싱·컨테이너·OCR·샷 체인지 검출이 압도적이라 그 위에 얹는 것이 맞다. 실사용자가 겪는 구멍은 다른 곳에 있다.

| 페인 포인트 | SE 실측 |
|---|---|
| 타임코드를 손으로 맞춰야 한다 | 부품(`TimeCodesBeautifier`·`DurationsBridgeGaps`·`ShotChangeHelper`)은 다 있는데 **하나씩 눌러야 하고 순서를 도구가 모른다** |
| Whisper에 검수가 없고 맥락을 놓친다 | 엔진 4종 래핑은 있으나 언어별 후처리가 `GermanNouns.cs` 하나뿐. 검수·신뢰도·화자 분리·용어집 주입 전무 |
| 가이드를 사람이 외워서 적용한다 | 넷플릭스 QC 17종은 전부 수치·형식. **표기 규칙 0건**, 위반 시 근거 조항을 못 댄다 |
| 자막 교정 기능이 없다 | `Dictionaries/`에 한국어 사전 0개. `AutoBreakLinePrivate`은 CJK면 어절 분리 경로를 아예 안 탄다 |

자세한 근거: [docs/SUBTITLEEDIT_ARCHITECTURE_ANALYSIS.md](docs/SUBTITLEEDIT_ARCHITECTURE_ANALYSIS.md)

## 구조

```
rules/      플랫폼 규정 프로파일 (순수 데이터, 코드 금지)
  SCHEMA.md     스키마 정의와 로더 계약
  netflix/      common / ko-translation / ko-sdh
  disney/       미확보
  coupang/      미확보
  sources/      사람이 읽는 근거 문서 — YAML은 여기서 파생된다
docs/       설계 문서
```

`rules/`에 코드를 넣지 않는 이유는 규정 데이터가 커지면 `git subtree split`으로 별도 저장소로 떼내기 위해서다. 규정은 자주 개정되고(넷플릭스 한국어 2025-07-07, 영어 2025-12-19), 개정 이력은 코드 커밋과 섞이면 안 된다.

## SDH와 번역 자막은 반드시 분리한다

같은 자막이라도 두 규정은 다르다. 넷플릭스 한국어 기준:

| | 번역 자막 | SDH |
|---|---|---|
| 읽기 속도(성인) | 12 CPS | **14 CPS** |
| 화자 표시 | 없음 | `[이름]` |
| 효과음 | 없음 | `[의성어/서술]` |
| 원문 충실도 | 압축·함축 허용 | **의역 금지** |

섞이면 오탐이 난다. 그래서 프로파일에 `kind: sdh | translation`을 필수로 두고, **SDH 전용 키가 번역 프로파일에 있으면 로더가 실패**하도록 계약을 정했다. 사람 기억이 아니라 스키마가 막는다.

## 원칙

- 규정 근거는 **플랫폼·정부 공식 문서만.** 블로그·2차 자료 수치는 프로파일에 넣지 않는다
- 못 구한 규정은 추측으로 채우지 않고 `status: unavailable`로 남긴다
- 위반 리포트는 **조항 번호를 인용한다**(`Korean TTSG I.13`)
- 근거가 간접적인 규칙은 자동 교정하지 않고 확인 플래그로 남긴다(`auto: false`)

## 한국어 계층

[korean-subtitle-corrector](https://github.com/tigermorning/korean-subtitle-corrector)를 엔진으로 붙인다. 그쪽은 일반 사용자용 범용 교정기로 유지하고, 자막 도메인 지식은 전부 이쪽이 갖는다. 경계 판정법: **"이 규칙을 이메일 원고에 적용해도 말이 되는가."** 되면 교정기, 안 되면 편집기.

## 미결정

- UI 스택 → 언어 결정 → libse 연동 방식(네이티브 참조 / CLI / 서비스)
- libse 포크 vs NuGet 의존
- `ko_NoBreakAfterList.xml` 업스트림 기여 여부

## 라이선스

미정. SubtitleEdit은 MIT라 파생 작업에 제약이 없다.

## 검사기 사용법

```bash
pip install -r requirements.txt

python -m checker examples/ko-sdh-sample.srt -p netflix -l ko -k sdh
python -m checker file.srt -p netflix -l en -k translation --json
python -m checker --list
```

`--children`를 붙이면 아동 프로그램 기준(더 느린 읽기 속도)을 적용한다.
종료 코드는 위반이 있으면 1, 없으면 0이다.

리포트는 위반마다 **조항 번호를 인용한다**. `[자동]`은 기계적으로 고칠 수 있는 것,
`[확인]`은 사람이 판단할 것이다. 프로파일에 있지만 아직 구현하지 않은 검사는
`미구현 검사`로 따로 출력한다 — 검사하지 않은 것을 통과로 보이게 하지 않는다.

코어는 JSON in / JSON out 순수 함수(`checker.check_events`)다. 편집기를 어떤
언어로 만들든 이 계약만 지키면 옮겨진다.

테스트: `python3 tests/run_tests.py`

### 한국어 교정 레인

`--korean`을 붙이면 [korean-subtitle-corrector](https://github.com/tigermorning/korean-subtitle-corrector)의
맞춤법·띄어쓰기 교정을 함께 돌린다.

```bash
python -m checker file.srt -l ko -k sdh --korean --ksc-path /path/to/korean-subtitle-corrector
# 또는 KSC_PATH 환경변수
```

**교정기에는 대사만 넘어간다.** 화자 표시 `[진수]`, 효과음 `[문 닫는 소리]`, 음표 `♪`,
2인 화자 하이픈, 서식 태그는 자막 문법이지 한국어가 아니다. `checker/korean.py`가
이것들을 벗겨 내고 대사 조각만 넘긴 뒤 결과를 제자리에 되돌린다 — 자막 지식은
편집기가, 한국어 지식은 교정기가 갖는다는 분리 원칙이 코드로 나타나는 자리다.

교정기 결과는 `source: corrector`로 표시되고 `K01`(교정 제안)·`K02`(확인 필요)로
분류된다. 자동 교정도 파일을 바로 바꾸지 않고 제안으로만 보고한다.

교정기는 kiwipiepy(약 310MB)와 국립국어원 API 키가 필요하다. 교정기 저장소의
가상환경 파이썬으로 이 검사기를 실행하는 것이 가장 간단하다.

### 자동 교정

`--fix`를 붙이면 기계적으로 고칠 수 있는 것을 고쳐 **새 파일**로 쓴다. 원본은
그대로 둔다 — 자동 교정이 틀렸을 때 되돌릴 수 있어야 하기 때문이다.

```bash
python -m checker file.srt -l ko -k sdh --fix            # file.fixed.srt 로 나간다
python -m checker file.srt -l ko -k sdh --fix -o out.srt
python -m checker file.srt -l ko -k sdh --fix --korean   # 교정기 결과까지 반영
```

고치는 것은 `auto: true`인 규칙 중 **고치는 함수가 등록된 것만**이다. 프로파일이
`auto: true`라고 말해도 기계가 정할 수 없는 자리가 있다(대괄호를 어디서 닫을지는
사람만 안다). 그런 규칙은 고치지 않고 `자동 표시지만 기계가 못 고치는 것`으로
따로 출력한다 — 고쳤다고 말하지 않는 것이 중요하다.

### 여러 파일 · 폴더

파일을 여러 개 주거나 폴더를 통째로 줄 수 있다. 시즌 한 벌을 한 번에 돌리는
형태다.

```bash
python -m checker 시즌1/ -l ko -k sdh --korean
python -m checker ep01.srt ep02.srt -l ko -k translation --fix
```

폴더는 한 단계만 훑고 `*.fixed.srt`는 다시 집지 않는다. 한국어 교정기는 파일마다
올리지 않고 **한 번만 적재한다** — 형태소 분석기가 무거워서 회차를 여러 개 돌릴 때
그 비용이 그대로 곱해진다. 마지막에 합계가 나오고, 위반이 하나라도 있으면 종료
코드는 1이다.

### Windows에서 끌어다 놓기

명령줄을 치지 않고 쓰는 방법이다. `tools/`의 .bat 파일 위로 **자막 파일이나
폴더를 끌어다 놓으면** 된다.

```
tools/
  check-ko-sdh.bat           넷플릭스 ko SDH — 검사만
  check-ko-translation.bat   넷플릭스 ko 번역 — 검사만
  check-en-translation.bat   넷플릭스 en 번역 — 검사만
  fix-ko-sdh.bat             검사 + 자동 교정(.fixed.srt 로 나감)
  fix-ko-translation.bat     검사 + 자동 교정
```

프로파일이 파일 이름으로 갈린다 — **SDH와 번역을 실수로 바꿔 쓸 일이 없다.**
결과는 화면에 뜨고 자막 파일 옆에 `checker-report.txt`로도 남는다.

파이썬은 `CHECKER_PYTHON` 환경변수 > 옆 폴더의 한국어 교정기 가상환경 > PATH 순으로
찾는다. 교정기가 옆에 있으면 한국어 교정 레인도 자동으로 함께 돈다(못 불러오면
건너뛰었다고 알리고 규정 검사는 계속한다).

바탕화면에서 쓰려면 .bat 파일의 **바로 가기**를 만들어 두면 된다.

### 발주처마다 다른 기준

규정은 절대적 정답이 아니라 **발주처가 요구하는 틀**이다. 같은 넷플릭스 작업이라도
에이전시가 자기 기준을 얹는다. 그래서 프로파일을 상속해 다른 부분만 덮어쓴다.

```yaml
extends: ../../rules/netflix/ko-translation.yaml
source:
  official: false
  client: "○○ 에이전시 2026년 자막 지침 v3"
limits:
  chars_per_line: 14      # 이 발주처는 14자
disable_rules: [T06]      # 점 3개 규칙은 끈다
```

```bash
python -m checker file.srt --profile my-profiles/agency-ko.yaml
```

공식 값이 개정되면 상속본도 따라간다. 리포트 머리에 **어떤 기준으로 쟀는지**가
나온다(문서명·개정일·발주처). 예시: `examples/profiles/agency-sample-ko-translation.yaml`

작업 전에 프로파일부터 맞춰 놓는 것이 순서다 — 틀이 다르면 정답도 다르다.

### 한국어 줄바꿈 검사

SE가 완전히 비어 있는 자리다 — `Dictionaries/`에 한국어 사전이 0개이고,
`Utilities.AutoBreakLinePrivate`은 CJK면 어절 분리 경로를 아예 타지 않아 한국어
줄바꿈이 글자 수 절단 수준이다.

두 줄 자막의 끊은 자리를 본다.

- 아랫줄이 **의존명사**로 시작(`것`·`수`·`때`…) — 앞말과 붙는 말이다
- 아랫줄이 **보조 용언**으로 시작(`있는`·`주다`…) — 본용언과 갈렸다
- 윗줄이 **관형사**로 끝남(`그`·`한`…) 또는 **관형형**으로 끝남(`목격된`·`일하는`…)
- 윗줄이 아랫줄의 2배 이상(`T18`, 권고. 위반이 아니라 별도 규칙이다)

형태소 분석기를 쓰지 않는다. 여기서 보는 것이 의존명사·보조 용언·관형사처럼
**닫힌 부류**라 목록이 유한하기 때문이고, 교정기의 kiwi를 부르면 적재에 1~2분이
걸려 줄바꿈 하나 보자고 치를 값이 아니기 때문이다.

**애매하면 말하지 않는다.** `차는`·`범인`처럼 조사·명사 어미가 관형형과 겹치는
형태는 형태소 분석 없이 가를 수 없어 검사 대상에서 뺐다. 실사용 자막 1,926개로
재어 오탐을 42건에서 5건으로 줄였고, 남은 5건은 전부 진짜였다.

### 타임코드 수렴 (`--fix-timing`)

영상 없이 자막 파일만으로 타임코드를 규정 안에 넣는다.

```bash
python -m checker file.srt -l ko -k sdh --fix-timing --fix
```

규칙끼리 충돌하므로(표시 시간을 늘리면 간격이 좁아지고, 간격을 벌리면 속도가 오른다)
우선순위를 정해 수렴시킨다.

```
1. 겹침 해소      2. 최소 표시 시간   3. 자막 간 간격
4. 최대 표시 시간  5. 읽기 속도
```

**인점은 되도록 건드리지 않는다** — 말이 시작되는 지점이라 소리와 어긋나면 바로
티가 난다. 아웃점만 뒤로 미는 것이 기본이고, 그것으로 안 되면 인점을 당긴다.

**끝내 못 맞춘 자리는 고쳤다고 하지 않는다.** "앞뒤 자막과 병합을 검토하세요",
"시간으로는 더 못 줄입니다. 글자를 줄이거나 자막을 나누세요"처럼 남은 문제로 알린다.

### 영상에서 읽기 (`--video`, `--spot`)

```bash
python -m checker file.srt -l ko -k sdh --video ep01.mkv --spot
```

- `--video` — ffprobe로 **프레임레이트와 길이**를 읽는다. 프레임 단위 규정(자막 간
  2프레임)이 정확해진다. 프레임레이트가 일정하지 않은 영상(화면 녹화물 등)은 그 사실을
  알린다
- `--spot` — ffmpeg으로 **말소리 구간**을 찾아 인점·아웃점을 제안한다

스포팅 기준은 작업자 자료를 그대로 따른다: 인점은 말소리 시작 2~3프레임 앞, 아웃점은
말소리 끝 6~9프레임 뒤, 다음 자막 인점을 넘지 않는다.

**제안만 하고 자동으로 고치지 않는다.** 말소리 검출은 음량 기준이라 배경음악이 크면
경계가 흐려지고, 그 값으로 타임코드를 덮어쓰면 싱크가 통째로 어긋난다.

ffmpeg은 `PATH`나 `FFMPEG_PATH`·`FFPROBE_PATH` 환경변수로 찾는다. 없으면 영상이
필요 없는 검사는 그대로 돌고 영상 기능만 건너뛴다.

#### 영상 자동 찾기

`--spot`을 쓰면서 `--video`를 안 주면 **자막 옆에서 같은 이름의 영상**을 찾는다
(`ep01.srt` -> `ep01.mkv`). `.fixed`·`_ko_TL` 같은 꼬리표는 떼고 찾는다.
그래서 `tools/spot-ko-sdh.bat` 아이콘에 자막만 끌어다 놓으면 된다.

#### ffmpeg 설치

영상 기능(`--video`·`--spot`)에만 필요하다. 없으면 그 기능만 건너뛰고 나머지는 돈다.

- Windows: https://www.gyan.dev/ffmpeg/builds/ 에서 release essentials 를 받아
  압축을 풀고 `bin` 폴더를 PATH에 넣는다
- 또는 압축만 풀고 `FFMPEG_PATH`·`FFPROBE_PATH` 환경변수로 실행 파일을 가리킨다

### 프로파일을 잘못 고르면 알려 준다

OTT마다 화자명·어조·음악·삐 처리 표기가 다르다. 그래서 자막만 보고도 어느 플랫폼
작업물인지 유추할 수 있다.

```
쿠팡      (철수)          소괄호 화자명
넷플릭스   [철수/작게]      슬래시로 나눈 대괄호
디즈니     [철수가 작게]    서술형 대괄호, [♪ 음악], O 삐 처리
```

고른 프로파일과 자막의 표기가 어긋나면 리포트 머리에 경고가 나온다.

```
⚠ 자막 표기는 coupang 쪽으로 보이는데 netflix 프로파일로 검사했습니다.
  근거: 소괄호 화자명 (철수), 점 셋 말줄임표. 프로파일을 확인하세요.
```

**확정하지 않는다.** 근거가 약하면 아무 말도 하지 않는다 — 애매한 근거로 사람을
흔들면 오히려 프로파일을 잘못 바꾸게 된다.

### 아이콘에 플랫폼이 드러난다

```
netflix-ko-sdh-check.bat / -fix.bat / -spot.bat
netflix-ko-translation-check.bat / -fix.bat / -spot.bat
netflix-ko-sdh-practice-check.bat     공식 규정 + 실무 관행
netflix-en-translation-check.bat
coupang-ko-sdh-check.bat / -fix.bat
disney-ko-sdh-check.bat / -fix.bat
```

번역 자막은 아직 넷플릭스만 있다. 디즈니·쿠팡의 번역 자막 규정은 확보하지 못했다
— 실무 자료가 SDH 기준이었다. 추측해 만들지 않는다.
