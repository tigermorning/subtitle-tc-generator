# 자막 및 TC 생성기

전문 번역가·자막 작업자를 위한 **초벌 생성기**. 영상 하나에서 전사 → 대조 → 번역 →
재분할 → 스포팅까지 이어 붙여 **1차 결과물**을 낸다. 세부 손질은 작업자가 쓰던
자막 편집기(SubtitleEdit)에서 이어서 한다.

**SubtitleEdit을 대체하지 않는다.** 2026-08-12에 사용자가 범위를 좁혔다 — SE를 흉내
내는 기능은 만들지 않는다. 가장 중요한 것은 **타임코드 생성과 자막 생성**이고, 나머지는
부차적이다. 목적은 편집기를 만드는 것이 아니라 **작업자의 시간을 줄이는 것**이다.

## 최상위 목표

**전문가가 신뢰하고 쓸 수 있으며, 전문가의 시간 낭비를 줄이는 도구.**

우선순위가 정해져 있고, 이것이 설계 결정을 여러 번 뒤집었다.

    자동 교정 오답 0  >  플래그 건수 감소  >  선택적 recall

대상 사용자는 맞춤법을 몰라서 이 도구를 쓰는 것이 아니다. 300줄에서 놓친 것을 잡으려고
쓴다. 그래서 틀린 자동 교정은 사람이 못 알아채고 신뢰를 깨뜨린다. recall 100%는 사전
커버리지가 상한이라 원리적으로 불가능하므로 도달 목표로 세우지 않는다.

## 왜 한 사람이 통째로 맡게 만드는가

지금까지 TC·번역·SDH는 **각각 따로 발주돼 왔다**(사용자 설명, 2026-09-10). 이유는
갈래마다 전문 분야가 다르고, **미디어 일이라 납기가 촉박하기 때문**이다 — 정해진
기간 안에 완성품을 내려면 여러 사람이 동시에 붙어 빨리 끝내는 수밖에 없었다.

번역은 특히 부가 업무가 많다. 드라마 같은 시리즈물은 한 사람이 다 못 맡고 **여러
번역자가 나눠 작업**하기 때문에, 말투(어조·존반)를 어느 정도 규격으로 정해 두고,
용어 통일을 위해 **KNP 엑셀 시트**를 따로 만들어 맞춘다. 이 저장소의
`checker/terms.py`·`knp.py`·`webterms.py`가 그 시트를 자동으로 뽑는 이유가 이것이다.

**이 프로젝트가 노리는 것은 그 분업을 한 사람 안으로 접는 것이다** — 한 사람이
`TC+SDH` 또는 `TC+번역`을 통째로 맡는다. 만드는 일은 도구가 빠르고 정확하게 하고,
**그 한 사람에게 남는 일은 도구가 낸 결과를 감수하는 것뿐이다.**
규칙 13(`CLAUDE.md`)의 "여럿이 붙어야 나오는 완성본을 전문가가 감수만 하면 될 만큼"이
같은 말이고, 이 절은 그 **이유**를 적는다.

## 두 저장소

| 저장소 | 하는 일 |
|---|---|
| **subtitle-tc-generator** (이 저장소) | 전사·번역·타임코드·발주처 규정 검사 |
| [korean-subtitle-corrector](https://github.com/tigermorning/korean-subtitle-corrector) | 규칙 + 국립국어원 API로 한국어를 교정한다. **AI를 쓰지 않는다** |

경계 판정법: **"이 규칙을 이메일 원고에 적용해도 말이 되는가."** 되면 교정기, 안 되면
여기다. 의존은 한 방향이다 — 이 저장소가 교정기를 라이브러리로 부르고(`checker/korean.py`),
교정기는 이 저장소를 모른다.

## 작업 단계

화면과 CLI가 같은 단계 모델(`checker/pipeline.py::STAGES`)을 쓴다. 어댑터가 순서를
따로 가지면 CLI와 화면이 갈라지므로, 순서는 파이프라인 한 곳에만 있다.

```
소재     [자막 만들기]                     영상 -> 전사 -> 재분할 -> 스포팅
번역     [① 1차 번역] [② 번역 감수 (회차)] [③ 자막 윤문·QA]
한국어   [② 한국어 교정] [③ 자막 QA]
조사     [용어표] [캐릭터 문서]
```

**단계마다 볼 것이 하나씩이다.** 1차는 오역만 본다(투박한 한국어는 괜찮다). 2차가
용어·맥락·말투를, 3차가 말맛·간결·문장부호와 **글자 수**를 본다. 글자 수를 앞 단계에서
맞추면 뜻이 먼저 깎인다. 같은 규칙이 두 단계에 겹치면 시험이 잡는다.

번역 트랙에는 검증 층이 붙는다.

    ① 1차 번역 직후   오역 검증 층1 — 원문과 전수 대조(화자 표시·용어·부정·숫자)
    ③ 끝            역번역 — 번역을 원어로 되돌려 원문과 견준다

## 쓰는 법 — 화면

Windows용 실행 파일이다. 파이썬이 없어도 돈다.

```
dist/자막생성기/자막생성기.exe
```

영상·파형·자막 표를 한 화면에 두고, 위 단계들을 단추와 `단계(&S)` 메뉴로 돌린다.
줄기마다 직전 결과 요약이 붙어 다음에 무엇을 할지 보인다.

- 영상 재생은 libmpv, 파형은 자체 계산이다
- 결과는 화면에 넘기기 **전에** `.work/`에 남는다 — 화면이 멈춰도 결과는 살아 있다
- [도움말 → 진단]이 무엇을 찾았고 무엇이 없는지 스스로 말한다

**사용자 자료는 `%APPDATA%\자막생성기\`에 있다**(전사 모델·프로파일·기록). 프로그램
폴더는 다시 빌드하면 통째로 지워지므로 큰 모델을 거기 두지 않는다. 옛 이름
(`자막편집기`) 폴더가 이미 있으면 그것을 계속 쓴다 — 이름을 바꿨다고 1.5GB 모델을
잃게 하지 않는다.

빌드:

```
cmd.exe /c "..\korean-subtitle-corrector\.venv\Scripts\python.exe -m PyInstaller \
  --noconfirm --distpath dist --workpath .tmp\build 자막생성기.spec"
```

## 쓰는 법 — 명령줄

```bash
pip install -r requirements.txt

python -m checker examples/ko-sdh-sample.srt -p netflix -l ko -k sdh
python -m checker file.srt -p netflix -l en -k translation --json
python -m checker --list
```

종료 코드는 위반이 있으면 1, 없으면 0이다. 리포트는 위반마다 **조항 번호를 인용한다**
(`Korean TTSG I.13`). `[자동]`은 기계가 고칠 수 있는 것, `[확인]`은 사람이 판단할
것이다. 프로파일에 있지만 아직 구현하지 않은 검사는 `미구현 검사`로 따로 낸다 —
**검사하지 않은 것을 통과로 보이게 하지 않는다.**

### 자막 만들기 (`--generate`)

```bash
python -m checker --generate --video ep01.mkv -l ko -k sdh          # SDH 초안
python -m checker --generate --video ep01.mkv --script ep01.docx \
                  -l ko -k translation --translate                   # 원어 대조 + 한국어 초벌
```

전사는 ffmpeg 내장 whisper, 말소리 구간은 Silero VAD(없으면 음량), 번역은 로컬
Ollama다. **원고가 이 컴퓨터 밖으로 나가지 않는다.** 원어 스크립트는 워드·텍스트·PDF를
읽는다.

전사와 스크립트는 **어느 쪽도 정답으로 두지 않는다.** 어긋난 자리는 기계가 정하지 않고
표시한다. 소리를 못 찾은 스크립트 줄은 지우지 않고 길이 0으로 남긴다.

### 화면 캡션·비대사 소리 (`--ocr` / `--sfx`)

whisper는 말소리만 받아 적는다 — 화면에 타 있는 글자, 대사 없는 구간의 효과음은
따로 읽어야 한다. 둘 다 **보고용 1단계(`--ocr-scan`/`--sfx-scan`)와 실제로 얹는
2단계(`--ocr`/`--sfx`)로 나뉜다**(규칙4 — 추정은 표시만, 확실한 것만 자동 반영).

```bash
python -m checker --ocr-scan --video ep01.mkv --ocr-lang ko          # 화면 캡션 목록만
python -m checker --generate --video ep01.mkv -l ko -k sdh \
                  --ocr --fn-marker bracket                          # 실제로 얹기(마커 필수)
python -m checker --ocr-hardsub --video ep01.mkv                     # 하드섭 -> 초안 srt
python -m checker --sfx-scan --video ep01.mkv                        # 소리 후보 목록만
```

- **화면 캡션**은 EasyOCR을 격리 venv(`.venv-ocr/`)에서 서브프로세스로 돌려 읽는다.
  `--ocr-hardsub`(임베디드 트랙이 없는 하드섭 영상, 71분 기준 최대 7~8시간짜리 스캔)는
  프레임마다 결과를 디스크에 남겨 절전·재부팅으로 끊겨도 이어서 돈다 — 결과는
  정답지가 아니다, 사람이 영상과 대조해 고친 뒤에만 학습 자료가 된다.
- **비대사 소리**는 AudioSet 오디오 분류(`MIT/ast-finetuned-audioset`)로 VAD가 이미
  "대사 없음"으로 확정한 구간이 무슨 소리 계열인지 짐작한다(`-l ko -k sdh` 전용).
  얹은 자리는 신뢰도와 무관하게 예외 없이 "확인 필요"로 표시된다 — 분위기·구체
  동작은 오디오만으로 못 정하기 때문이다.

### 번역 (`--translate`)

```bash
python -m checker file.srt -l ko -k translation --translate --passes 3
python -m checker file.srt ... --max-passes 6 --settle-at 2     # 잠잠해지면 멈춘다
python -m checker file.srt ... --backtranslate                   # 역번역 검증
python -m checker file.srt ... --cast ep01.characters.tsv        # T17(말투 어긋남)
```

회차 상한은 시간 보호용이고, **상한에 걸린 것과 다 끝난 것을 문구로 갈라 적는다.**
회차마다 1차 대비로도 재서 누적 표류를 막는다(실측: 가드 없이 3회차 2.70배 → 가드
켜면 1.40배).

역번역은 **임계값을 두지 않는다.** 자르는 것은 점수가 아니라 개수다
(`--backtranslate-worst`, 기본 20) — 몇 점 이하가 오역인지는 실제 작업물로 재야 알고,
재기 전에 박으면 오답 공장이 된다.

### 한국어 교정 (`--korean`)

```bash
python -m checker file.srt -l ko -k sdh --korean --ksc-path /path/to/korean-subtitle-corrector
# 또는 KSC_PATH 환경변수. 옆 폴더에 있으면 그냥 찾는다
```

**교정기에는 대사만 넘어간다.** 화자 표시 `[진수]`, 효과음 `[문 닫는 소리]`, 음표 `♪`,
2인 화자 하이픈, 서식 태그는 자막 문법이지 한국어가 아니다. `checker/korean.py`가
이것들을 벗겨 내고 대사 조각만 넘긴 뒤 결과를 제자리에 되돌린다.

교정기 결과는 `source: corrector`로 표시되고 `K01`(교정 제안)·`K02`(확인 필요)로
갈린다. 교정기는 kiwipiepy(약 310MB)와 국립국어원 API 키가 필요하다 — 없으면 그
레인만 건너뛰고 규정 검사는 계속한다.

### 자동 교정 (`--fix`)

```bash
python -m checker file.srt -l ko -k sdh --fix            # file.fixed.srt 로 나간다
python -m checker file.srt -l ko -k sdh --fix -o out.srt
```

**원본을 덮어쓰지 않는다.** 고치는 것은 `auto: true`인 규칙 중 **고치는 함수가 등록된
것만**이다. 프로파일이 `auto: true`라고 말해도 기계가 정할 수 없는 자리가 있다(대괄호를
어디서 닫을지는 사람만 안다). 그런 규칙은 `자동 표시지만 기계가 못 고치는 것`으로 따로
낸다 — 고쳤다고 말하지 않는 것이 중요하다.

**검사는 맨 끝이다.** 원본만 검사하면 교정이 만든 새 위반을 못 본다(`3천 불` →
`3천 달러`가 글자 수 한계를 넘긴 실측 사례가 시험에 박혀 있다).

### 타임코드

```bash
python -m checker file.srt -l ko -k sdh --fix-timing --fix   # 영상 없이 규정 안으로
python -m checker file.srt -l ko -k sdh --video ep01.mkv --spot
python -m checker file.srt ... --lock-timecodes               # 절대 건드리지 않는다
```

수렴 우선순위: 겹침 해소 → 최소 표시 시간 → 자막 간 간격 → 최대 표시 시간 → 읽기 속도.
**인점은 되도록 건드리지 않는다** — 말이 시작되는 지점이라 어긋나면 바로 티가 난다.
끝내 못 맞춘 자리는 고쳤다고 하지 않고 남은 문제로 알린다.

`--lock-timecodes`는 실무에서 가장 흔한 경우를 위한 것이다(TC 작업이 끝난 파일을 받아
번역만 한다). 수렴·스포팅뿐 아니라 **재분할도 막는다** — 나누면 경계가 새로 생긴다.
`--fix-timing`과 함께 주면 조용히 무시하지 않고 오류로 막는다.

### 중간 결과 (`.work/`)

기본으로 켜져 있다(`--no-work`로 끈다).

```
ep01.work/
    manifest.json      단계별 모델·시각·걸린 시간·바뀐 줄·멈춘 이유
    01-generate.srt    타임코드 확정본 (이후 불변)
    01-source.json     번호별 원문
    02-first.srt
    03-revise-2차.srt  회차마다 따로
```

15분 걸린 번역이 3차에서 깨지면 처음부터 하게 된다 — 실사용에서 그것이 가장 비쌌다.
타임코드는 첫 단계에서 굳고, 이후 단계가 옮기면 기록에 경고로 남는다. **남기기가
실패해도 본 작업은 멈추지 않는다.**

### 조사 도구

```bash
python -m checker file.srt --terms                      # 용어표(KNP 시트용)
python -m checker file.srt --characters --wiki breakingbad --work-title "Breaking Bad"
python -m checker --bookmarks 폴더/                      # SE 북마크(강사 첨삭) 모으기
python -m checker file.srt --against 정답.srt            # 정답 자막과 대조해 값으로 잰다
```

**`--against`는 정답 영상을 지우기 전에 돌린다.** 영상(음성)이 없으면 `--generate`로
다시 초안을 못 만들어 이 대조를 다시 할 수 없다 — 목적은 사람이 연습하는 게 아니라
정답 없는 실전에서도 통하는 `checker/` 코드 자체를 검증·수정하는 것이다(CLAUDE.md
규칙 13). 절차는
[`.claude/skills/정답지-대조-진단/`](.claude/skills/정답지-대조-진단/SKILL.md)에
코드화돼 있다. 이 진단이 매 영상 필요한 건 아니다 — 같은 발주처+장르에서 연속
3편 새 구조 버그가 없으면 "성숙"으로 보고 그다음부턴 아래 정답지-학습만으로도
충분할 수 있다(`rules/private/corpus/corpus_status.yaml`의 `genre_maturity`가 이 판단을 기록한다).

캐릭터 문서는 KNP 시트와 **다른 문서다** — KNP는 고유명사 표기를, 이것은 말투와 인물
관계를 통일한다. 하나의 작품을 여러 작업자가 나누어 하기 때문에 필요하다. 밖으로
조회할 때 **나가는 것은 작품 제목과 인물 이름뿐이고, 대사·대본은 어떤 경우에도 나가지
않는다.** 무엇을 보냈는지 기록에 남긴다. 위키는 사람이 지정한다(`--wiki`) — 슬러그를
짐작하면 엉뚱한 인물 정보가 나오고, 그건 없는 것보다 나쁘다.

### Windows에서 끌어다 놓기

`tools/`의 .bat 파일 위로 자막 파일이나 폴더를 끌어다 놓으면 된다. 파일 이름에
플랫폼이 드러나므로 **SDH와 번역을 실수로 바꿔 쓸 일이 없다.**

```
netflix-ko-sdh-check.bat / -fix.bat / -spot.bat
netflix-ko-translation-check.bat / -fix.bat / -spot.bat
netflix-ko-sdh-practice-check.bat     공식 규정 + 실무 관행
netflix-en-translation-check.bat
disney-ko-sdh-check.bat / -fix.bat
disney-ko-translation-check.bat / -fix.bat
coupang-ko-sdh-check.bat / -fix.bat
coupang-ko-translation-check.bat / -fix.bat
```

**세 플랫폼 모두 SDH와 번역 프로파일이 있다.** 다만 근거의 성격이 다르고, 리포트 머리에
그것이 나온다.

| | 근거 | `official` |
|---|---|---|
| 넷플릭스 | Korean TTSG (2025-07-07 개정) | **true** |
| 디즈니+ | 작업자 실무 자료 (작업 기본 원칙) | false |
| 쿠팡플레이 | 작업자 실무 자료 (작업 기본 원칙) | false |

디즈니·쿠팡의 **공식 문건**은 아직 못 구했다(파트너·벤더 전용이고 공개 웹에는 2차
정보뿐이다 — `rules/*/UNAVAILABLE.yaml`에 확보 경로와 미확인 항목을 적어 두었다).
그래서 웹에 도는 수치는 넣지 않았고, 실무 자료가 정한 것만 넣었다. 규칙 수가 넷플릭스
(16개)보다 적은 것은 그 때문이다 — **빈칸을 추측으로 채우지 않은 결과다.** 발주처가
다른 값을 주면 그쪽이 우선이고, 공식 문건을 구하면 `official` 프로파일로 갈아 끼운다.

## 규정 프로파일

```
rules/
  SCHEMA.md     스키마 정의와 로더 계약
  genre/        documentary / drama / variety
  lexicon/      효과음 사전 등
  learned/      코퍼스에서 관측한 값(발주처별 버킷). 규정 파일이 아니다 — 아래 참고
  private/      *** 이 저장소에 없다. 아래 참고 ***
    netflix/    common / ko-sdh / ko-translation / en-translation
    disney/     ko-sdh / ko-translation
    coupang/    ko-sdh / ko-translation
    sources/    사람이 읽는 근거 문서 — 위 YAML은 여기서 파생된다
```

### 발주처 공식 규정은 별도 비공개 저장소에 있다

넷플릭스·디즈니+·쿠팡플레이 규정과 그 원문 발췌는 **파트너 전용 비공개 문서**다.
계약이 걸린 자료라 미공개 영상·대본과 같은 이유로 이 저장소에 두지 않는다
(`CLAUDE.md` 규칙 6). `.gitignore`가 `rules/private/`를 막고 있다.

받으려면 비공개 규정 저장소를 그 자리에 클론한다:

```bash
git clone git@github.com:tigermorning/subtitle-tc-rules.git rules/private
```

없어도 프로그램은 돈다 — **그 세 발주처 프로파일만 안 보인다.** `genre`·`lexicon`·
`learned`와 사용자가 만든 프로파일은 그대로다. 로더(`checker/profile.py`의
`_roots()`)가 `rules/private/`를 함께 뒤지므로, **부르는 이름은 예전과 같다**:
`-p netflix -l ko -k sdh`, `extends: netflix/ko-translation.yaml`.

시험도 마찬가지다. `rules/private/`가 없으면 규정 프로파일을 쓰는 시험이
"규정 프로파일을 찾지 못했습니다"로 멈춘다 — 조용히 건너뛰지 않는다.

### 학습 계층 (`rules/learned/`)

정답 자막에서 관측한 통계(글자 수·CPS·듀레이션·간격 분포)를 발주처별로 쌓아 둔다
(`tools/corpus_build.py`). **공식 규정을 절대 덮어쓰지 않는다** — `source.origin:
learned`로 출처를 구분하고, 규정으로 승격하려면 사람 확인을 거친다(CLAUDE.md
규칙 11). 절차는 [`.claude/skills/정답지-학습/`](.claude/skills/정답지-학습/SKILL.md)에
코드화돼 있다. 정답지 있는 영상은 이 학습부터 예외 없이 먼저 하고, 위 `--against`
진단(비용 큰 whisper 필요)은 그 뒤 필요할 때만 한다(CLAUDE.md 규칙 13).

`rules/`에 코드를 넣지 않는다. 규정은 자주 개정되고, 개정 이력이 코드 커밋과 섞이면
안 된다(나중에 `git subtree split`으로 떼낼 수 있게 둔다).

### SDH와 번역 자막은 반드시 분리한다

같은 자막이라도 두 규정은 다르다. 넷플릭스 한국어 기준:

| | 번역 자막 | SDH |
|---|---|---|
| 읽기 속도(성인) | 느리다 | **빠르다** |
| 화자 표시 | 없음 | `[이름]` |
| 효과음 | 없음 | `[의성어/서술]` |
| 원문 충실도 | 압축·함축 허용 | **의역 금지** |

섞이면 오탐이 난다. 프로파일에 `kind: sdh | translation`을 필수로 두고, **SDH 전용 키가
번역 프로파일에 있으면 로더가 실패한다.** 사람 기억이 아니라 스키마가 막는다.

### 발주처 기준 (상속)

규정은 절대적 정답이 아니라 발주처가 요구하는 틀이다.

```yaml
extends: netflix/ko-translation.yaml   # 자리 대신 이름 — 로더가 뒤져 찾는다
source:
  official: false
  client: "○○ 에이전시 2026년 자막 지침 v3"
limits:
  chars_per_line: 14
disable_rules: [T06]
```

공식 값이 개정되면 상속본도 따라간다. 리포트 머리에 **어떤 기준으로 쟀는지**가 나온다
(문서명·개정일·발주처).

### 장르 (`--genre`)

장르는 프롬프트가 아니라 **프로파일 층**이다. 작업자 자료 590행이 장르로 타임코드
길이를 가르므로 검사기가 볼 수 있어야 한다.

```
다큐(정통/리얼)   ~씨 금지, TC 3~5초, 합니다체 위주
드라마            ~씨 가능, TC 2~3초          ← 멜로가 여기 들어간다
예능/리얼다큐     TC 2초 이하
```

멜로·느와르 프로파일은 **만들지 않는다.** 멜로는 드라마 기본값이고, 거친 표현은 장르가
아니라 **캐릭터**가 정한다(검열 금지는 이미 플랫폼 규정이다).

다큐 합니다체는 **비율만 낸다.** "다큐는 합니다체 위주이지만 자연스러움을 위해 가끔
`요`를 쓰는 것은 허용된다"는 것이 작업자 확인이다. 허용되는 것을 위반으로 부르면
오답이므로, 임계값은 완성본 자막으로 재기 전까지 두지 않는다.

### 화면자막 겹침 (`checker/position.py`)

말자막과 화면 번인 자막(forced narrative)이 겹칠 때 어떻게 처리할지는 **플랫폼이
아니라 매 작업마다** 정해진다(작업자 자료가 "업체마다 다르고 같은 업체도 작업마다
달라진다"고 명시). 그래서 프로파일 기본값에 못 박지 않고 `--fn-marker`(화면자막
표식)·`--collision`(옮김/삭제/둘 다 유지)로 작업 시작 전에 받는다. 정하지 않으면
위치 검사 자체를 하지 않는다 — 추측해서 옮기면 납품물이 틀어진다.

## SubtitleEdit과의 관계

작업자가 이미 SE를 쓰고 있고(실사용 4.0.15), 세부 손질은 거기서 한다. 그래서 SE를
대체하는 대신 **SE 안에서 우리 검사·교정을 부를 수 있게** 했다.

| | SE 4.x (사용자가 쓰는 것) | SE 5 |
|---|---|---|
| 형태 | net48 DLL, SE 프로세스 안 | 독립 실행 파일 + JSON |
| 우리 구현 | `plugin/se4/` (동작 확인됨, 설치돼 있다) | `checker/plugin.py` |

SE가 못 하는 자리를 우리가 채운다 — 한국어 표기 규정, 위반 조항 인용, 한국어 맞춤법
(SE `Dictionaries/`에 한국어 사전 0개), 한국어 줄바꿈. 근거:
[docs/SUBTITLEEDIT_ARCHITECTURE_ANALYSIS.md](docs/SUBTITLEEDIT_ARCHITECTURE_ANALYSIS.md),
사용법: [docs/SE_PLUGIN.md](docs/SE_PLUGIN.md)

SE에서 가져온 코드는 두 자리뿐이고 둘 다 **바꾸면 안 되는 것**이라 옮겼다. 목록과 근거는
[docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)에 있다.

## 한국어 줄바꿈 검사

SE가 완전히 비어 있는 자리다. 두 줄 자막의 끊은 자리를 본다.

- 아랫줄이 **의존명사**로 시작(`것`·`수`·`때`…)
- 아랫줄이 **보조 용언**으로 시작(`있는`·`주다`…)
- 윗줄이 **관형사**·**관형형**으로 끝남(`그`·`한`·`목격된`…)
- 윗줄이 아랫줄의 2배 이상(`T18`, 권고)

형태소 분석기를 쓰지 않는다 — 여기서 보는 것이 닫힌 부류라 목록이 유한하고, 교정기의
kiwi를 부르면 적재에 1~2분이 걸린다. **애매하면 말하지 않는다.** 실사용 자막 1,926개로
재어 오탐을 42건에서 5건으로 줄였고, 남은 5건은 전부 진짜였다.

## 원칙

전체는 [`CLAUDE.md`](CLAUDE.md)(규칙 13개)에 있다. 요약:

- 단계 순서를 섞지 않는다. **글자 수는 마지막이다**
- 원어에 한국어 규정을 적용하지 않는다
- **어느 쪽도 정답으로 두지 않는다** — 어긋나면 기계가 정하지 않고 표시한다
- 확실한 근거와 추정을 구분한다. 추정으로 자동 교정하지 않는다
- 규정은 절대적 정답이 아니다. 공식 문건과 실무 자료를 구분하고 개정일을 적는다
- **미공개 자료는 밖으로 내보내지 않는다.** 전사·번역 전부 로컬
- 원본을 덮어쓰지 않는다 / 받은 타임코드는 건드리지 않는다
- 자료가 없는 프로파일·임계값을 추측해서 만들지 않는다
- **학습이 규정을 건드리지 않는다.** 코퍼스에서 관측한 값(`rules/learned/`)은
  공식 규정 파일(`rules/<platform>/`)을 절대 고치지 못한다 — 승격은 사람 확인을
  거친다
- **정답지 대조는 도구 검증이지 "연습"이 아니다.** 정답이 있는 드문 기회로
  `checker/` 코드의 구조적 버그를 찾아 고친다 — 정답 없는 실전에서도 그 고침이
  그대로 통한다

## 개발

```bash
python3 tests/run_tests.py     # 1141건 (GUI 제외)
cmd.exe /c "..\korean-subtitle-corrector\.venv\Scripts\python.exe tests\run_tests.py"   # 1141건
```

시스템 파이썬에는 PySide6가 없다. `app/`을 건드리면 venv 쪽으로도 돌린다.

커밋은 훅이 막는다. 새 클론·워크트리에서 한 번 켠다:

```bash
git config core.hooksPath tools/hooks
```

`tools/hooks/pre-commit`이 시험을 돌리고, 실패하면 커밋이 만들어지지 않는다. 규칙을
글로만 두었을 때 세 번 뚫렸기 때문에 기계로 옮겼다.

다음 작업자를 위한 인수 문서는 [docs/BACKLOG.md](docs/BACKLOG.md)에 있다 — 무엇이 남았고
왜 그 순서인지가 거기 있다.

## 라이선스

미정. 함께 배포하는 남의 것(libmpv·Silero VAD·PySide6)과 그 조건은
[docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)에 있다.
