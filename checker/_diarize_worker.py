"""화자 분리 워커 — **격리 venv(`.venv-diarize`)에서만 돈다.**

`diarize.py`가 이 파일을 서브프로세스로 부른다. 직접 import해서 쓰지 않는다 —
pyannote.audio가 시스템 파이썬의 torch(다른 프로젝트가 물려 쓴다)와 다른
버전을 요구해서 별도 venv에 있다(`docs/HANDOFF.md` 참고). 그래서 이 파일은
`checker` 패키지에 기대지 않고 표준 라이브러리 + pyannote.audio만 쓴다 —
격리 venv에는 PyYAML 같은 `checker`의 다른 의존성이 없다.

사용법: `python _diarize_worker.py <영상 경로> <출력 json 경로> [모델 이름]`
환경변수: `HF_TOKEN`(또는 `HUGGINGFACE_TOKEN`), `PYANNOTE_MODEL_DIR`(완전
로컬 사용 시 — 이게 있으면 토큰이 필요 없다)
출력: `[[시작ms, 끝ms, "SPEAKER_00"], ...]` 형태 JSON을 두 번째 인자 경로에 쓴다.
성공하면 0, 실패하면 표준에러에 이유를 적고 0이 아닌 값으로 끝난다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# **자기 폴더를 sys.path 맨 앞에서 뺀다.** 이 파일이 `checker/` 안에 있어서
# 파이썬이 이 파일을 스크립트로 실행하면 `checker/`가 sys.path[0]이 된다.
# `checker/profile.py`(우리 프로파일 로더)가 표준 라이브러리 `profile` 모듈을
# 가려서, torch 내부가 `import cProfile` -> `import profile`을 할 때 엉뚱한
# 모듈을 가져와 깨진다(실측, 2026-08-27: `AttributeError: module 'profile' has
# no attribute 'run'`). 격리 venv에는 `checker` 패키지가 아예 없으니 이 파일이
# `checker/`에 기대는 것도 없다 — 그냥 위치만 같이 두었을 뿐이라 빼도 안전하다.
_own_dir = str(Path(__file__).resolve().parent)
if _own_dir in sys.path:
    sys.path.remove(_own_dir)

import json
import os
import shutil
import subprocess
import tempfile

SAMPLE_RATE = 16000
DEFAULT_MODEL = "pyannote/speaker-diarization-community-1"


def _add_ffmpeg_dll_dir() -> None:
    """pyannote.audio(정확히는 torchcodec)가 오디오를 읽으려면 ffmpeg 공유
    라이브러리(avcodec 등 DLL)가 있어야 한다. Python 3.8부터 Windows는
    `ctypes.CDLL`이 의존 DLL을 찾을 때 실행 파일 폴더도 자동으로 안 본다 —
    `os.add_dll_directory()`로 직접 알려줘야 한다(실측, 2026-08-27). DLL은
    이 venv의 `Scripts/`(= `sys.executable`이 있는 폴더)에 둔다고 정했다."""
    scripts_dir = Path(sys.executable).parent
    if scripts_dir.is_dir() and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(scripts_dir))


def _read_audio_wav(video: Path, work: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg를 찾지 못했습니다(PATH에 없음).", file=sys.stderr)
        sys.exit(2)
    out_path = work / "diarize.wav"
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-v", "error", "-y",
         "-i", str(video), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), str(out_path)],
        capture_output=True, check=False,
    )
    if result.returncode != 0 or not out_path.is_file():
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()[:200]
        print(f"오디오를 읽지 못했습니다: {detail}", file=sys.stderr)
        sys.exit(2)
    return out_path


def main() -> int:
    if len(sys.argv) < 3:
        print("사용법: _diarize_worker.py <영상> <출력.json> [모델]", file=sys.stderr)
        return 2
    video = Path(sys.argv[1])
    out_json = Path(sys.argv[2])
    model = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_MODEL

    _add_ffmpeg_dll_dir()
    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        print(f"pyannote.audio가 설치돼 있지 않습니다: {exc}", file=sys.stderr)
        return 2

    local_dir = os.environ.get("PYANNOTE_MODEL_DIR")
    if local_dir:
        pipeline = Pipeline.from_pretrained(local_dir)
    else:
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            print("HF_TOKEN(또는 HUGGINGFACE_TOKEN) 환경변수가 없습니다.", file=sys.stderr)
            return 2
        try:
            pipeline = Pipeline.from_pretrained(model, token=token)
        except Exception as exc:
            print(f"화자 분리 모델을 불러오지 못했습니다: {exc}", file=sys.stderr)
            return 2

    with tempfile.TemporaryDirectory(prefix="stc-diarize-") as tmp:
        wav = _read_audio_wav(video, Path(tmp))
        output = pipeline(str(wav))

    turns = [[int(turn.start * 1000), int(turn.end * 1000), str(speaker)]
             for turn, speaker in output.speaker_diarization]
    turns.sort(key=lambda t: t[0])
    out_json.write_text(json.dumps(turns), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
