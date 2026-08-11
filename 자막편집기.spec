# -*- mode: python ; coding: utf-8 -*-
"""실행 파일 만들기 설정.

**무엇을 넣고 무엇을 안 넣는지가 핵심이다.**

    넣는다      화면(PySide6) · 엔진(checker) · 규정 파일(rules) · VAD 모델(2MB)
                libmpv(영상 재생, LGPL이라 함께 배포할 수 있다)

    안 넣는다   whisper 모델(1.5GB) · ffmpeg · Ollama · 한국어 교정기

안 넣는 것들은 **프로그램이 알아서 찾는다.** 1.5GB 모델을 실행 파일에 넣으면 내려받기
부터가 일이고, ffmpeg은 사용자가 이미 가진 경우가 많다. 없으면 어디서 받는지 알려
주는 것이 낫다.
"""

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("rules", "rules"),                       # 프로파일·규정. 없으면 검사가 안 된다
    ("models/silero_vad.onnx", "models"),     # 말소리 검출. 2MB라 함께 넣는다
]

binaries = [("bin/libmpv-2.dll", ".")]

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=(collect_submodules("checker") + collect_submodules("app")
                   + ["mpv", "onnxruntime", "numpy", "pypdf"]),
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="자막편집기",
    console=False,            # 검은 창을 띄우지 않는다
    icon=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="자막편집기",
)
