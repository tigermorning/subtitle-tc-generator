"""프로그램이 쓰는 자리들.

**프로그램 폴더와 사용자 자료를 섞지 않는다.** 실행 파일을 다시 만들면 그 폴더는
통째로 지워진다 — 거기 모델을 두면 빌드할 때마다 1.5GB를 다시 넣어야 한다(실제로
그랬다, 2026-08-12).

    프로그램 폴더    실행 파일, 규정, 작은 모델(VAD)      다시 만들면 지워진다
    사용자 자료      큰 모델, 발주처 기준, 기록           남는다
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data() -> Path:
    """사용자 자료 폴더. Windows는 `%APPDATA%\\자막편집기`."""
    override = os.environ.get("SUBTITLE_EDITOR_HOME")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "자막편집기"


def model_dirs() -> list[Path]:
    """모델을 찾을 자리들. **사용자 자료가 먼저다** — 거기 둔 것이 오래 남는다."""
    beside_exe = Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent.parent
    bundled = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", "") else None
    places = [user_data() / "models", beside_exe / "models", beside_exe]
    if bundled:
        places.append(bundled / "models")
    places += [here / "models", here / ".tmp", Path.home() / "whisper-models"]
    return places
