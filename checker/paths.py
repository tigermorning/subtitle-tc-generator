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
    """사용자 자료 폴더. Windows는 `%APPDATA%\\자막생성기`.

    **옛 이름(`자막편집기`) 폴더가 이미 있으면 그것을 계속 쓴다.** 저장소 이름을
    바꿨다고 사용자 자료를 잃게 하면 안 된다(2026-08-12 결정) — 여기에는
    `settings.json`, 로그, 발주처 규정 프로파일, 그리고 whisper 모델
    (`ggml-large-v3-turbo.bin` 약 1.5GB)이 들어 있다. 이름만 바꾸면 사용자는 설정을
    잃고 모델을 다시 받아야 한다.

    **옮기지 않는다.** 1.5GB를 이동하는 코드는 그 자체가 실패 지점이다(권한, 중간에
    끊김, 드라이브 부족). 옛 폴더를 그냥 계속 읽는 쪽이 잃을 것이 없다. 새로 쓰는
    사람만 새 이름을 갖는다.

    이름 길이도 봤다. `자막생성기`는 `자막편집기`와 같은 5자다 — whisper가 한글 경로
    모델을 못 여는 문제를 하드링크로 우회해 두었는데(`transcribe.py::_ascii_model_path`)
    경로 길이가 그대로라 그 우회를 다시 시험하지 않는다.

    표시 이름(창 제목·진단 창)은 새 이름을 쓴다. **표시 이름과 저장 위치는 별개다.**
    """
    # **환경변수 이름은 바꾸지 않는다.** 테스트·문서·사용자 설정이 참조하는 공개
    # 계약이다(2026-08-12: 이름을 바꿨다가 테스트 두 건이 깨져 되돌렸다). 표시 이름과
    # 계약은 별개다 — 폴더 이름도 같은 이유로 옛 것을 계속 읽는다.
    override = os.environ.get("SUBTITLE_EDITOR_HOME")
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    new, old = base / "자막생성기", base / "자막편집기"
    if not new.exists() and old.exists():
        return old
    return new


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
