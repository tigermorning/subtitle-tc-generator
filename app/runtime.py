"""프로그램이 돌기 위해 필요한 것들을 찾는다.

**엔진은 `checker/`에 이미 있다.** 이 폴더는 껍데기(화면)만 만든다 — 전사·번역·검사는
전부 그쪽을 부른다. 두 벌로 만들면 반드시 어긋난다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 실행 파일로 묶이면 자료가 임시 폴더에 풀린다. 그 자리를 먼저 본다.
FROZEN = getattr(sys, "frozen", False)
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def add_engine_to_path() -> None:
    """`checker` 패키지를 불러올 수 있게 한다."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def data_root() -> Path:
    """규정 파일·모델이 있는 자리. 묶였으면 풀린 자리, 아니면 저장소."""
    return ROOT


def find_libmpv() -> Path | None:
    """libmpv를 찾는다.

    **배포할 때는 우리 것을 실어야 한다.** libmpv는 LGPL이라 함께 배포할 수 있지만,
    남의 프로그램 설치 폴더에서 빌려 쓰는 것은 개발 중에만 할 일이다. 사용자가
    Subtitle Edit을 지우면 우리 프로그램이 멈춘다.
    """
    names = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll")
    # 묶인 프로그램은 자기 폴더에 dll을 들고 다닌다.
    places = [ROOT, ROOT / "bin", ROOT / ".tmp",
              Path(sys.executable).resolve().parent]
    appdata = os.environ.get("APPDATA")
    if appdata:
        places.append(Path(appdata) / "Subtitle Edit")     # 개발 중 임시
    for folder in places:
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None


def prepare_mpv() -> str | None:
    """libmpv가 있는 폴더를 PATH에 넣는다. 없으면 어디서 받는지 알려 준다."""
    found = find_libmpv()
    if not found:
        return None
    folder = str(found.parent)
    if folder not in os.environ.get("PATH", ""):
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
    return folder


MPV_MISSING = (
    "libmpv를 찾지 못했습니다. 영상 재생에 필요합니다.\n"
    "  https://github.com/shinchiro/mpv-winbuild-cmake/releases 에서 "
    "mpv-dev 꾸러미를 받아 libmpv-2.dll을 bin/ 폴더에 두세요."
)
