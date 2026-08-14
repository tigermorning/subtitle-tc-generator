# 함께 배포하는 남의 것

실행 파일에 넣어 배포하는 것들과 그 조건이다. **조건을 어기면 배포를 못 한다.**

## libmpv (LGPL v2.1 이상)

영상 재생에 쓴다. `bin/libmpv-2.dll`.

- 출처: https://github.com/shinchiro/mpv-winbuild-cmake/releases (공식 Windows 빌드)
- LGPL이라 **함께 배포할 수 있다.** 다만 두 가지를 지켜야 한다.
  1. 라이선스 전문을 함께 넣는다.
  2. 사용자가 이 라이브러리를 **자기 것으로 바꿔 끼울 수 있어야** 한다 — 우리는
     DLL을 폴더에서 찾아 쓰므로(정적으로 묶지 않는다) 파일만 바꾸면 된다.
- **Subtitle Edit이 설치한 것을 빌려 쓰지 않는다.** 개발 중에는 그렇게 했지만,
  사용자가 SE를 지우면 멈추는 프로그램을 팔 수 없다.

## Silero VAD (MIT)

말소리 구간 검출. `models/silero_vad.onnx` (2MB).

- 출처: https://github.com/snakers4/silero-vad
- MIT라 넣어 배포할 수 있다.

## PySide6 (LGPL v3)

화면. LGPL 조건은 libmpv와 같다 — 동적으로 이어 쓰고 바꿔 끼울 수 있어야 한다.
PyInstaller가 별도 파일(`_internal/PySide6/`)로 넣으므로 조건을 만족한다.

## 넣지 않는 것

프로그램이 실행할 때 **찾아 쓰는** 것들이다. 배포물에 들어가지 않는다.

| | 왜 안 넣나 |
|---|---|
| ffmpeg | 크고, 사용자가 이미 가진 경우가 많다. 없으면 어디서 받는지 알려 준다 |
| whisper 모델 | 1.5GB. 배포물에 넣으면 내려받기부터 일이 된다 |
| Ollama·번역 모델 | 5GB. 번역을 안 쓰는 사람에게 강요할 수 없다 |
| 한국어 교정기 | 별개 프로그램이다. 있으면 빌려 쓰고 없으면 규정 검사만 한다 |

## Subtitle Edit (MIT)

**거의 안 쓴다. 다만 "한 줄도 없다"는 것은 사실이 아니었다** — 2026-08-14에 공식
저장소(`subtitleedit-src`, 얕은 클론)를 실제로 열어 대조하고 이 절을 고쳤다.

**라이선스가 바뀌어 있다.** `LICENSE`와 `installer/LICENSE.rtf` 둘 다 **MIT**다
(Copyright (c) 2026 Nikolaj Olsson). 여기 GPL이라고 적어 두었던 것은 옛 정보다.
MIT는 저작권 표시만 함께 넣으면 되므로 우리 배포에 조건이 걸리지 않는다.
**다만 우리가 옮긴 부분이 옛 GPL 판에서 온 것이면 그 판의 조건을 따른다** — 아래
두 자리는 현재 판(MIT)의 파일과 대조해 확인했다.

SE에서 온 것 둘:

| 자리 | 무엇 | 왜 옮겼나 |
|---|---|---|
| `plugin/se4/IPlugin.cs` | 플러그인 인터페이스 선언 24행 | **계약이라 바꿀 수 없다.** SE가 리플렉션으로 이 이름을 찾는다. 한 글자만 달라도 플러그인을 못 알아본다 |
| `checker/text.py::_CJK_RANGES` | CJK 유니코드 블록 11개 | SE `src/libse/Common/TextLengthCalculator/CalcCJK.cs::IsCjk`와 **같은 표다.** 글자 수를 SE와 다르게 세면 같은 자막에 두 프로그램이 다른 답을 낸다 |

`IPlugin.cs`는 본 저장소가 아니라 `SubtitleEdit/plugins` 쪽에서 왔다(파일 첫 줄에
출처를 적어 두었다). **그 저장소의 라이선스는 아직 직접 확인하지 않았다.**

**그 밖에는 코드가 아니라 계약과 사실만 따랐다** — SE5 플러그인 JSON 규약
(`checker/plugin.py`), 북마크 파일 형식(`checker/bookmarks.py`), 장면 전환·파형에
쓰는 ffmpeg 필터(`checker/media.py`), 작업자 손버릇에서 온 단축키 배치
(`app/shortcuts.py`). 구현은 전부 우리 것이다. 배포물(`dist/`)에 SE 파일은 없다.

**빌려 쓰는 자리 둘(배포물에 들어가지는 않는다).** `app/runtime.py`가 libmpv를,
`checker/media.py`가 ffmpeg을 `%APPDATA%\Subtitle Edit\`에서도 찾는다. libmpv 쪽은
**우리 것을 먼저 보고**(`bin/`, 실행 파일 옆) 없을 때만 거기까지 가며, 배포물에는
`_internal/libmpv-2.dll`이 실려 있으므로 SE가 없어도 돈다. 주석에 "개발 중 임시"라고
적혀 있는 그대로다.

## 배포물 옆에 두는 것

실행 파일 폴더 옆에 두면 프로그램이 찾아 쓴다. **없어도 그 기능만 안 된다** —
[도움말 → 진단]이 무엇이 없는지 알려 준다.

    프로그램 폴더 — 다시 만들면 **통째로 지워진다**
      자막생성기\
        자막생성기.exe
        _internal\                  프로그램이 만든 것. 건드리지 않는다

    사용자 자료 — %APPDATA%\자막생성기\ — **남는다**
      models\
        ggml-large-v3-turbo.bin     전사 모델(1.5GB). 없으면 전사만 안 된다
      profiles\                     발주처 기준

**옛 이름(`자막편집기`) 폴더가 이미 있으면 그것을 계속 쓴다.** 저장소 이름을 바꿨다고
사용자 자료를 잃게 하지 않는다 — 여기 모델 1.5GB와 설정이 들어 있어 이름을 바꾸면 사용자가
그것을 잃는다. 옮기지도 않는다 — 1.5GB 이동은 그 자체가 실패 지점이다. 자세한 이유는
`checker/paths.py::user_root` 참고. **표시 이름과 저장 위치는 별개다.**
      log.txt                       기록

큰 모델을 프로그램 폴더에 두었다가 다시 빌드할 때마다 날려 먹었다(2026-08-12).
자료는 프로그램과 따로 둔다.

한국어 교정기는 `KSC_PATH` 환경변수로 폴더를 알려 준다.

