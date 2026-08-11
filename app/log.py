"""무슨 일이 있었는지 파일에 남긴다.

**창만 보고는 왜 안 되는지 알 수 없다.** 사용자가 "아무 동작도 안 한다"고 했을 때
확인할 것이 아무것도 없었다(2026-08-12). 오래 걸리는 일은 겉으로 조용하기 때문에,
돌고 있는지 멈춘 것인지 구분되지 않는다.

로그는 `%APPDATA%\\자막편집기\\log.txt`에 쌓인다. 진단 창에서 자리를 알려 준다.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import traceback
from pathlib import Path

_handle = None


def log_path() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    folder = base / "자막편집기"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "log.txt"


def write(message: str) -> None:
    """한 줄 남긴다. **로그 때문에 프로그램이 죽으면 안 된다.**"""
    global _handle
    try:
        if _handle is None:
            path = log_path()
            # 너무 커지면 잘라낸다. 오래된 것보다 최근 것이 쓸모 있다.
            if path.exists() and path.stat().st_size > 2_000_000:
                path.unlink()
            _handle = path.open("a", encoding="utf-8")
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        _handle.write(f"{stamp}  {message}\n")
        _handle.flush()
    except Exception:
        pass


def install_excepthook() -> None:
    """어디서 터지든 로그에 남긴다. 조용히 사라지지 않게."""
    def hook(kind, value, tb):
        write("터짐: " + "".join(traceback.format_exception(kind, value, tb)))
        sys.__excepthook__(kind, value, tb)

    sys.excepthook = hook
    write(f"=== 시작 {_dt.datetime.now():%Y-%m-%d %H:%M:%S}")
