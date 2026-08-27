"""누가 말하는지(화자 구간)를 찾는다. **whisper는 이 정보를 안 준다.**

`regroup.py`는 whisper 조각을 이어 붙일 때 간격(`MAX_GAP_MS`)만 본다 — 화자가
바뀌었는지는 모른다. 그래서 두 사람이 빠르게 주고받는 자리(예능·토크)에서 서로
다른 사람의 말을 한 자막으로 묶어 버린다(실측: 예능A 15회 영어 번역,
2026-08-27 — "미스터 조?"/"미스터 조는 넌 아니야?" 주고받기가 whisper 환청과
겹쳐 한 덩어리로 묶였다).

이 모듈은 pyannote.audio로 화자 구간을 찾아 `regroup.merge_cues()`에 건넨다 —
간격이 짧아도 **화자가 바뀌는 자리는 합치지 않는다.**

**밖으로 나가지 않는다.** 오디오는 이 컴퓨터를 떠나지 않는다. 모델 파일은
Hugging Face에서 한 번 받아 로컬에 둔다(규칙 6과 같은 방식 — whisper·VAD 모델도
같은 자리에서 받는다).

**추정이다.** 화자 분리도 모델이고 모델은 틀린다. 그래서 결과는 병합 단계의
"합치지 않을 근거"로만 쓰고, 이미 사람이 정한 화자 표기(SDH 화자명 등)를
덮어쓰는 데는 쓰지 않는다.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .media import MediaToolUnavailable, _as_tool_path, _find

SAMPLE_RATE = 16000

# 3.1은 게이팅된 두 모델(segmentation-3.0 + speaker-diarization-3.1)을 따로
# 동의해야 했다. community-1은 정확도가 더 낫고 화자 수 세기가 개선됐고,
# 전사 타이밍에 맞추기 좋은 "exclusive" 모드가 있다 — 우리 용도(합칠지 말지
# 판단)에 정확히 맞는다(2026-08-27 확인, huggingface.co/pyannote/
# speaker-diarization-community-1).
DEFAULT_MODEL = "pyannote/speaker-diarization-community-1"


class DiarizationUnavailable(Exception):
    """pyannote.audio가 없거나, 모델·토큰이 없다."""


def _find_token(explicit: str | None = None) -> str | None:
    return explicit or os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")


def _read_audio_wav(video: Path, work: Path) -> Path:
    """16kHz 모노 WAV로 뽑는다. pyannote가 파일 경로를 직접 받는다."""
    out_path = work / "diarize.wav"
    result = subprocess.run(
        [_find("ffmpeg"), "-hide_banner", "-nostats", "-v", "error", "-y",
         "-i", _as_tool_path(video), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
         _as_tool_path(out_path)],
        capture_output=True, check=False,
    )
    if result.returncode != 0 or not out_path.is_file():
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise MediaToolUnavailable(f"오디오를 읽지 못했습니다: {detail}")
    return out_path


def _load_pipeline(model: str, token: str | None):
    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise DiarizationUnavailable(
            "pyannote.audio가 설치돼 있지 않습니다. 받으세요:\n"
            "  pip install pyannote.audio\n"
            "그리고 https://hf.co/settings/tokens 에서 토큰을 만들고 "
            f"https://huggingface.co/{DEFAULT_MODEL} 에서 이용 약관에 동의한 뒤\n"
            "  HF_TOKEN=<토큰> 환경변수로 알려 주세요.\n"
            "(완전한 로컬 사용은 모델을 git-lfs로 내려받아 폴더 경로를 "
            "PYANNOTE_MODEL_DIR로 지정하세요 — 토큰이 그 뒤로는 필요 없습니다.)"
        ) from exc

    local_dir = os.environ.get("PYANNOTE_MODEL_DIR")
    if local_dir:
        return Pipeline.from_pretrained(local_dir)

    if not token:
        raise DiarizationUnavailable(
            "Hugging Face 토큰이 없습니다. https://hf.co/settings/tokens 에서 "
            "만들고, https://huggingface.co/" + DEFAULT_MODEL + " 에서 이용 약관에 "
            "동의한 뒤 HF_TOKEN 환경변수로 알려 주세요."
        )
    try:
        return Pipeline.from_pretrained(model, token=token)
    except Exception as exc:  # 토큰은 있는데 약관 미동의 등 — pyannote가 자기 메시지를 낸다
        raise DiarizationUnavailable(f"화자 분리 모델을 불러오지 못했습니다: {exc}") from exc


def find_speaker_turns(video: Path, model: str | None = None, token: str | None = None,
                       progress=None) -> list[tuple[int, int, str]]:
    """화자 구간 [(시작ms, 끝ms, 화자표)] — 시간순, 실제 화자 이름이 아니라 SPEAKER_00 같은 임시 표.

    사람이 정한 화자명(SDH `[이름]`)과 이 표는 **다른 것이다** — 이건 "같은
    사람인지 다른 사람인지"만 구분하는 내부용 표다.
    """
    say = progress or (lambda _m: None)
    pipeline = _load_pipeline(model or DEFAULT_MODEL, _find_token(token))

    with tempfile.TemporaryDirectory(prefix="stc-diarize-") as tmp:
        work = Path(tmp)
        wav = _read_audio_wav(Path(video), work)
        say("화자를 구분합니다 — 영상 길이에 비례해 걸립니다...")
        output = pipeline(str(wav))

    turns: list[tuple[int, int, str]] = []
    for turn, _, speaker in output.speaker_diarization:
        turns.append((int(turn.start * 1000), int(turn.end * 1000), str(speaker)))
    turns.sort(key=lambda t: t[0])
    say(f"화자 구간 {len(turns)}개")
    return turns


def speaker_at(ms: int, turns: list[tuple[int, int, str]]) -> str | None:
    """이 시각에 말하고 있던 화자표. 구간 사이(짧은 침묵)면 None — 모르면 억지로 답하지 않는다."""
    for start, end, label in turns:
        if start <= ms <= end:
            return label
    return None
