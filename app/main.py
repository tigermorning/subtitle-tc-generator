"""독립 실행 자막 편집기 — 시작점.

    python -m app

SE 플러그인과 **같은 엔진**을 쓴다. 화면만 우리 것이다.
"""

from __future__ import annotations

import sys

from .runtime import add_engine_to_path, prepare_mpv


def main() -> int:
    add_engine_to_path()
    prepare_mpv()          # libmpv가 없어도 창은 뜬다. 영상만 안 나온다.

    from PySide6.QtWidgets import QApplication
    from .window import MainWindow

    application = QApplication(sys.argv)
    application.setApplicationName("자막 편집기")
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
