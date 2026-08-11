# Subtitle Edit 플러그인으로 쓰기

## 왜 플러그인인가

새 편집기를 맨땅에서 만들면 **몇 년 동안 SE보다 못한 물건**이 된다. SE는 커밋
26,000개에 자막 포맷 408종·OCR·파형·샷 체인지·Whisper 래핑을 갖고 있고 지금도
갱신된다. "적어도 SE에 뒤지지 않아야 한다"를 만족하는 형태는 하나뿐이다 —
**사용자가 SE를 그대로 쓰고, 거기에 우리 것이 더해지는 것**이다.

뺄셈이 없다. SE가 하던 일은 전부 그대로 있고 다음이 더해진다.

| | SE | 플러그인이 더하는 것 |
|---|---|---|
| 한국어 표기 규정 | 없음 | 넷플릭스 ko SDH·번역 프로파일 |
| 위반 근거 | 못 댄다 | 조항 인용(`Korean TTSG II.9`) |
| 한국어 맞춤법 | 사전 0개 | 사전·어문 규범 기반 교정 |
| 되돌리기 | — | SE가 undo 지점을 만들어 준다 |

## SE5 플러그인 규약 (요약)

SE5 플러그인은 **독립 실행 파일 + JSON 파일**이다. SE4의 인프로세스 WinForms DLL
방식과 완전히 다르다.

1. 사용자가 SE 메뉴에서 플러그인을 고른다
2. SE가 임시 폴더에 `request.json`을 쓴다
3. SE가 **플러그인 실행 파일을 `request.json` 경로를 인자로** 띄운다
4. 플러그인이 일하고 `responseFilePath`에 `response.json`을 쓴 뒤 0으로 종료
5. SE가 `status: ok`면 **undo 지점을 만들고** 자막을 교체한다

request에 들어오는 것 중 우리가 쓰는 값:

    subtitle.subRip        자막 전체를 SRT로 (우리 파서가 그대로 읽는다)
    settings               지난번 우리가 돌려준 설정을 그대로 돌려준다
    pluginDataDirectory    플러그인 전용 영구 폴더(업데이트해도 안 지워진다)
    tempDirectory          이번 실행용 임시 폴더

아직 안 쓰지만 나중에 P1·P2에 쓸 값: `videoFileName`, `frameRate`,
`videoPositionSeconds`, `selectedIndices`, `themeColors`.

## 설정

플러그인은 아직 자기 창이 없다. 설정은 두 곳에서 온다(뒤가 이긴다).

1. `<pluginDataDirectory>/config.json` — 사용자가 손으로 고치는 파일
2. SE가 왕복시켜 주는 `settings` — 지난 실행에서 우리가 돌려준 값

```json
{
  "platform": "netflix",
  "language": "ko",
  "kind": "sdh",
  "children": false,
  "applyFixes": true,
  "korean": false,
  "kscPath": "C:\\Users\\...\\korean-subtitle-corrector",
  "spacing": "principle"
}
```

- `kind` — `sdh` 또는 `translation`. **이 값이 검사 기준을 가른다**(읽기 속도
  14 대 12 CPS 등). 기본값은 `translation`이다
- `applyFixes` — `false`면 검사만 하고 자막을 건드리지 않는다
- `korean` — 한국어 교정기 레인. `kscPath`가 필요하다

## 결과 보기

SE는 응답의 `message` 한 덩어리만 보여준다. 그래서 요약만 거기 담고, 조항까지
붙은 **전체 리포트는 `<pluginDataDirectory>/last-report.txt`에 쓴다.** 메시지에
그 경로가 나온다.

```
netflix ko sdh 기준 위반 13건 (자동 교정 가능 2건, 확인 필요 11건)
자막 2줄을 고쳤습니다. 전체 리포트: ...\last-report.txt
```

## 만들기

플러그인은 실행 파일이어야 하므로 파이썬 코드를 PyInstaller로 묶는다.

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --name subtitle-rule-checker \
    --add-data "rules:rules" \
    -c checker/plugin.py
```

`rules/`를 함께 넣는 이유는 프로파일 YAML이 실행 파일 옆에 있어야 하기 때문이다.

## 설치

SE 데이터 폴더(`Settings.json` 옆)의 `Plugins/` 아래에 폴더 하나로 넣는다.

```
Plugins/
  SubtitleRuleChecker/
    plugin.json
    subtitle-rule-checker.exe
    rules/
```

SE에서 **Plugins → Manage plugins…** 로 확인한다. 메뉴가 안 보이면
**Options → Settings → Appearance → Show Plugins menu**를 켠다.

## 개발 중 시험

실행 파일로 묶기 전에 요청 파일을 직접 만들어 돌릴 수 있다.

```bash
python -m checker.plugin /path/to/request.json
```

`responseFilePath`가 비어 있으면 응답을 표준 출력으로 낸다.

## 한계와 다음

플러그인이 막는 것은 하나다 — **타이핑하는 즉시 피드백.** 플러그인은 메뉴를
눌러야 돈다. 그것이 실제로 아프면 그때 SE를 포크한다(MIT라 가능하다). 그때도
검사기 코어(`check_events`, 프로파일 YAML)는 그대로 옮겨간다. JSON in/out으로
짜 둔 값이 여기서 나온다.
