"""독립 실행 자막 및 TC 생성기 — 시작점.

    python -m app

SE 플러그인과 **같은 엔진**을 쓴다. 화면만 우리 것이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .runtime import add_engine_to_path, prepare_mpv


def main() -> int:
    from .log import install_excepthook, write
    install_excepthook()

    add_engine_to_path()
    prepare_mpv()
    write("엔진·재생기 준비 완료")          # libmpv가 없어도 창은 뜬다. 영상만 안 나온다.

    # 묶인 프로그램은 화면 없이 확인할 길이 없다. 진단 결과를 파일로 남기고 끝낸다.
    if "--selftest" in sys.argv:
        from .diagnose import as_text
        report = as_text()
        Path(sys.executable).with_name("진단.txt").write_text(report, encoding="utf-8")
        # 창 없는 프로그램이라 표준 출력이 cp949이거나 아예 없다. 파일이 본체이고
        # 화면 출력은 덤이므로, 여기서 죽지 않게 감싼다.
        try:
            print(report)
        except (UnicodeEncodeError, OSError, AttributeError):
            pass
        return 0

    from PySide6.QtWidgets import QApplication
    from .window import MainWindow

    application = QApplication(sys.argv)
    application.setApplicationName("자막 및 TC 생성기")
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
