"""실행 파일의 진입점.

**`app/main.py`를 직접 진입점으로 삼으면 안 된다.** PyInstaller는 그 파일을 패키지
밖에서 `__main__`으로 돌리는데, 그러면 `from .runtime import ...` 같은 상대 임포트가
"attempted relative import with no known parent package"로 죽는다(실측).

여기서 `app`을 **패키지로** 불러오면 그 안의 상대 임포트가 정상으로 풀린다.
"""

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
