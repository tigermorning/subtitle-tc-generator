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

## 어느 SE에 붙일 것인가

두 가지 규약이 있고 **호환되지 않는다.**

| | SE 4.x (현재 배포판) | SE 5 (개발 중) |
|---|---|---|
| 형태 | net48 DLL, SE 프로세스 안에서 돈다 | 독립 실행 파일 + JSON 주고받기 |
| 자리 | `%appdata%\Subtitle Edit\Plugins` | 같은 폴더, 실행 파일 |
| 우리 구현 | `plugin/se4/` (**동작 확인됨**) | `checker/plugin.py`, `plugin/plugin.json` |

사용자가 실제로 쓰는 것은 **4.0.15**라 SE4 쪽이 먼저다. SE5 어댑터는 그대로 두고,
SE5가 배포되면 그때 그 경로로 넘어간다.

## SE4 플러그인 — 빌드와 설치

.NET SDK가 필요 없다. Windows에 이미 있는 `csc.exe`로 빌드한다.

```
cd plugin\se4
%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe -nologo -target:library ^
  -out:SubtitleRuleChecker.dll -r:System.dll -r:System.Drawing.dll ^
  -r:System.Windows.Forms.dll -optimize+ IPlugin.cs Plugin.cs Runner.cs PluginForm.cs
copy SubtitleRuleChecker.dll "%APPDATA%\Subtitle Edit\Plugins\"
```

SE를 다시 켜면 **[도구] 메뉴**에 `자막 규정 검사·교정 / 영상에서 자막 만들기...`가
생긴다(2026-08-11 실제 확인).

`IPlugin.cs`는 SubtitleEdit/plugins 저장소의 것을 **그대로** 옮긴 것이다. SE가
리플렉션으로 찾으므로 한 글자만 달라도 플러그인이 보이지 않는다. 고치지 말 것.

`csc.exe`는 C# 5까지만 안다. 표현식 본문 멤버(`=>`)를 쓰면 빌드가 깨진다. 빌드에
SDK를 요구하지 않는 값이 그 불편보다 크다.

## 플러그인이 하는 일

| 버튼 | 하는 일 |
|---|---|
| 검사만 | 규정·한국어 검사. 자막은 그대로 둔다 |
| 검사 + 교정 | 고칠 수 있는 것을 고친 결과를 만든다 |
| 영상에서 자막 만들기 | 전사 -> (대본 대조) -> (번역) -> 재분할 -> 스포팅 |

**[SE에 반영]을 누르기 전에는 SE의 자막이 바뀌지 않는다.** 리포트를 먼저 보고
사람이 결정한다. 반영한 뒤에도 SE에서 Ctrl+Z로 되돌릴 수 있다.

일은 전부 파이썬이 한다. DLL은 다리일 뿐이다 — 규정 검사와 교정이 C#에도 구현되면
두 벌을 함께 고쳐야 하고, 그러면 반드시 어긋난다.

### 플러그인이 스스로 찾는 것들

| 무엇 | 어떻게 |
|---|---|
| 검사기 저장소 | `CHECKER_REPO` -> ini -> `내 문서\subtitle-editor` -> 물어본다 |
| 파이썬 | `CHECKER_PYTHON` -> 교정기 `.venv` -> PATH |
| ffmpeg | PATH -> winget 폴더 -> **SE가 딸려 보내는 것** |
| whisper 모델 | `WHISPER_MODEL` -> `models/`의 가장 큰 것 |

한 번 찾은 것은 `%appdata%\Subtitle Edit\Plugins\subtitle-rule-checker.ini`에
적어 두고 다시 묻지 않는다.

**전사에는 ffmpeg 9.0 이상이 필요하다.** SE가 딸려 보내는 것은 8.0이라 whisper
필터가 없다. 플러그인이 필터 목록을 확인해 있는 쪽을 고르고, 없으면 무엇을 깔아야
하는지 말한다.

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
