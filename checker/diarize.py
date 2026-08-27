"""누가 말하는지(화자 구간)를 찾는다. **whisper는 이 정보를 안 준다.**

`regroup.py`는 whisper 조각을 이어 붙일 때 간격(`MAX_GAP_MS`)만 본다 — 화자가
바뀌었는지는 모른다. 그래서 두 사람이 빠르게 주고받는 자리(예능·토크)에서 서로
다른 사람의 말을 한 자막으로 묶어 버린다(실측: 예능A 15회 영어 번역,
2026-08-27 — "미스터 조?"/"미스터 조는 넌 아니야?" 주고받기가 whisper 환청과
겹쳐 한 덩어리로 묶였다).

이 모듈은 pyannote.audio로 화자 구간을 찾아 `regroup.merge_cues()`에 건넨다 —
간격이 짧아도 **화자가 바뀌는 자리는 합치지 않는다.**

**실제 작업은 격리된 venv(`.venv-diarize`)의 서브프로세스가 한다.**
pyannote.audio가 torch>=2.8.0을 요구하는데, 시스템 파이썬의 torch는 다른
도구(torchvision 등)가 물려 써서 버전을 못 올린다 — 실제로 한 번 올렸다가
시스템 torch를 깨뜨려 되돌린 적이 있다(2026-08-27, `docs/HANDOFF.md` 참고).
그래서 이 모듈(시스템 파이썬에서 import된다)은 pyannote를 직접 import하지
않는다 — `_diarize_worker.py`를 격리 venv의 파이썬으로 실행해서 결과만
JSON으로 받는다.

**밖으로 나가지 않는다.** 오디오는 이 컴퓨터를 떠나지 않는다. 모델 파일은
Hugging Face에서 한 번 받아 로컬에 둔다(규칙 6과 같은 방식 — whisper·VAD 모델도
같은 자리에서 받는다).

**추정이다.** 화자 분리도 모델이고 모델은 틀린다. 그래서 결과는 병합 단계의
"합치지 않을 근거"로만 쓰고, 이미 사람이 정한 화자 표기(SDH 화자명 등)를
덮어쓰는 데는 쓰지 않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

# 3.1은 게이팅된 두 모델(segmentation-3.0 + speaker-diarization-3.1)을 따로
# 동의해야 했다. community-1은 정확도가 더 낫고 화자 수 세기가 개선됐고,
# 전사 타이밍에 맞추기 좋은 "exclusive" 모드가 있다 — 우리 용도(합칠지 말지
# 판단)에 정확히 맞는다(2026-08-27 확인, huggingface.co/pyannote/
# speaker-diarization-community-1).
DEFAULT_MODEL = "pyannote/speaker-diarization-community-1"


class DiarizationUnavailable(Exception):
    """격리 venv가 없거나, pyannote.audio·모델·토큰이 없거나, 서브프로세스가 실패했다."""


def _find_token(explicit: str | None = None) -> str | None:
    return explicit or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")


def _find_diarize_python() -> Path:
    """격리 venv의 파이썬을 찾는다. `DIARIZE_PYTHON`으로 다른 자리를 알려줄 수 있다."""
    override = os.environ.get("DIARIZE_PYTHON")
    if override and Path(override).is_file():
        return Path(override)

    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        repo_root / ".venv-diarize" / "Scripts" / "python.exe",   # Windows
        repo_root / ".venv-diarize" / "bin" / "python",           # POSIX
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise DiarizationUnavailable(
        "화자 분리용 격리 환경(.venv-diarize)을 찾지 못했습니다. "
        "pyannote.audio는 시스템 파이썬과 다른 torch 버전을 요구해 별도 venv에 "
        "설치합니다(docs/HANDOFF.md 참고):\n"
        "  python -m venv .venv-diarize\n"
        "  .venv-diarize/Scripts/python.exe -m pip install pyannote.audio\n"
        "다른 자리에 있으면 DIARIZE_PYTHON 환경변수로 python.exe 경로를 알려주세요.")


def find_speaker_turns(video: Path, model: str | None = None, token: str | None = None,
                       progress=None) -> list[tuple[int, int, str]]:
    """화자 구간 [(시작ms, 끝ms, 화자표)] — 시간순, 실제 화자 이름이 아니라 SPEAKER_00 같은 임시 표.

    사람이 정한 화자명(SDH `[이름]`)과 이 표는 **다른 것이다** — 이건 "같은
    사람인지 다른 사람인지"만 구분하는 내부용 표다.
    """
    say = progress or (lambda _m: None)
    diarize_python = _find_diarize_python()
    worker = Path(__file__).with_name("_diarize_worker.py")

    env = dict(os.environ)
    found_token = _find_token(token)
    if found_token:
        env["HF_TOKEN"] = found_token

    say("화자를 구분합니다 — 영상 길이에 비례해 걸립니다...")
    with tempfile.TemporaryDirectory(prefix="stc-diarize-") as tmp:
        out_json = Path(tmp) / "turns.json"
        args = [str(diarize_python), str(worker), str(video), str(out_json)]
        if model:
            args.append(model)
        result = subprocess.run(args, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", env=env)
        if result.returncode != 0 or not out_json.is_file():
            detail = (result.stderr or "").strip()
            detail = detail[-500:] if detail else f"종료 코드 {result.returncode}"
            raise DiarizationUnavailable(f"화자 분리에 실패했습니다: {detail}")
        turns = [(int(s), int(e), str(label))
                 for s, e, label in json.loads(out_json.read_text(encoding="utf-8"))]

    say(f"화자 구간 {len(turns)}개")
    return turns


def speaker_at(ms: int, turns: list[tuple[int, int, str]]) -> str | None:
    """이 시각에 말하고 있던 화자표. 구간 사이(짧은 침묵)면 None — 모르면 억지로 답하지 않는다."""
    for start, end, label in turns:
        if start <= ms <= end:
            return label
    return None
