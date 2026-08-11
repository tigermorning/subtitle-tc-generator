# 자막 편집기 (작업 중)

전문 번역가·자막 작업자를 위한 자막 편집기. SubtitleEdit보다 **자동화 수준이 높고 정확도가 높은 것**을 목표로 한다.

> 아직 코드는 없다. 규정 데이터와 설계 문서만 있다.

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
