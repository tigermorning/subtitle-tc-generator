"""말소리 구간을 **모델로** 찾는다.

`media.detect_speech`는 음량으로 찾는다. 그래서 음악이 깔린 내레이션에서 경계가
흐려진다 — 전문가 타임코드와 대조했을 때 흩어짐이 ±800ms까지 벌어진 자리가 전부
그런 구간이었다(2026-08-11, 연습 과제 6편).

이 모듈은 Silero VAD(2MB짜리 ONNX 모델)로 같은 일을 한다. 음량이 아니라 **소리의
모양**을 보고 사람 말인지 판단하므로 음악·잡음에 덜 흔들린다.

**여전히 추정이다.** 모델도 틀린다. 그래서 결과는 `detect_speech`와 같은 자리에
쓰이고(제안·생성 경로), 사람이 잡은 타임코드를 덮어쓰는 데는 쓰지 않는다.

**밖으로 나가지 않는다.** 모델 파일 하나를 로컬에서 돌린다. 오디오는 이 컴퓨터를
떠나지 않는다.

없으면 조용히 없다고 알리고, 부르는 쪽이 음량 검출로 되돌아간다 — 새 기능이
없다고 기존 경로가 멈추면 안 된다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .media import MediaToolUnavailable, _as_tool_path, _find, _known_places

SAMPLE_RATE = 16000
WINDOW = 512          # Silero v5는 16kHz에서 512 샘플(32ms) 단위로 본다
# **앞 64샘플을 함께 넣어야 한다.** 문맥 없이 512개만 넣으면 모델이 전 구간을
# 침묵으로 본다(확률이 0.003을 넘지 않았다). 파이썬 래퍼가 조용히 해 주던 일이라
# ONNX를 직접 부를 때 놓치기 쉽다.
CONTEXT = 64


class VadUnavailable(Exception):
    """모델이나 실행기가 없다."""


def find_model(explicit: str | None = None) -> Path:
    """`silero_vad.onnx`를 찾는다."""
    import os

    for value in (explicit, os.environ.get("VAD_MODEL")):
        if value and Path(value).is_file():
            return Path(value)
    here = Path(__file__).resolve().parent.parent
    for folder in (here / "models", here / ".tmp", Path.home() / "whisper-models"):
        candidate = folder / "silero_vad.onnx"
        if candidate.is_file():
            return candidate
    raise VadUnavailable(
        "silero_vad.onnx를 찾지 못했습니다. models/ 폴더에 두거나 VAD_MODEL로 "
        "경로를 지정하세요. https://github.com/snakers4/silero-vad 에서 받습니다(2MB).")


def _read_audio(video: Path):
    """16kHz 모노 PCM으로 읽는다. ffmpeg이 이미 있으니 그것을 쓴다."""
    import numpy as np

    result = subprocess.run(
        [_find("ffmpeg"), "-hide_banner", "-nostats", "-v", "error",
         "-i", _as_tool_path(video), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "s16le", "-"],
        capture_output=True, check=False,
    )
    if result.returncode != 0 or not result.stdout:
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise MediaToolUnavailable(f"오디오를 읽지 못했습니다: {detail}")
    return np.frombuffer(result.stdout, dtype=np.int16).astype("float32") / 32768.0


def detect_speech(video: Path, threshold: float = 0.5,
                  min_speech_ms: int = 120, min_silence_ms: int = 250,
                  pad_ms: int = 0, model: str | None = None,
                  progress=None) -> list[tuple[int, int]]:
    """말소리 구간 [(시작ms, 끝ms)]. `media.detect_speech`와 계약이 같다.

    같은 계약을 지키는 이유는 **바꿔 끼워 가며 잴 수 있어야** 하기 때문이다.
    어느 쪽이 나은지는 자료가 정하지, 새 것이라고 이기는 게 아니다.
    """
    try:
        import numpy as np
        import onnxruntime
    except ImportError as exc:
        raise VadUnavailable(f"onnxruntime이 필요합니다: {exc}") from exc

    say = progress or (lambda _m: None)
    model_path = find_model(model)
    audio = _read_audio(Path(video))
    say(f"말소리를 모델로 찾습니다 — {len(audio) / SAMPLE_RATE:.0f}초")
    probabilities = _probabilities(audio, model_path)
    return _spans(probabilities, threshold, min_speech_ms, min_silence_ms, pad_ms,
                  total_ms=int(len(audio) / SAMPLE_RATE * 1000))


def _probabilities(audio, model_path):
    """프레임(32ms)마다 사람 말일 확률. 값을 바꿔 가며 잴 때 이것만 한 번 구한다."""
    import numpy as np
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.inter_op_num_threads = 1
    options.intra_op_num_threads = 1
    session = onnxruntime.InferenceSession(str(model_path), options,
                                           providers=["CPUExecutionProvider"])
    state = np.zeros((2, 1, 128), dtype="float32")
    rate = np.array(SAMPLE_RATE, dtype="int64")
    context = np.zeros(CONTEXT, dtype="float32")

    probabilities = []
    for start in range(0, len(audio) - WINDOW + 1, WINDOW):
        chunk = audio[start:start + WINDOW]
        window = np.concatenate((context, chunk)).reshape(1, -1)
        out, state = session.run(None, {"input": window, "state": state, "sr": rate})
        probabilities.append(float(out[0][0]))
        context = chunk[-CONTEXT:]
    return probabilities


def _spans(probabilities, threshold: float, min_speech_ms: int,
           min_silence_ms: int, pad_ms: int, total_ms: int) -> list[tuple[int, int]]:
    """확률 열을 구간으로 바꾼다.

    **짧은 침묵으로 말을 끊지 않는다.** 문장 안의 숨은 침묵이지 자막 경계가 아니다.
    거꾸로 아주 짧은 말소리는 기침·잡음일 수 있어 버린다.
    """
    step = WINDOW * 1000 // SAMPLE_RATE          # 32ms
    speaking = False
    start_index = 0
    spans: list[tuple[int, int]] = []

    for i, probability in enumerate(probabilities):
        if not speaking and probability >= threshold:
            speaking, start_index = True, i
        elif speaking and probability < threshold:
            # 여기서 바로 끊지 않는다. 침묵이 충분히 길어야 끝으로 본다.
            silence = 0
            j = i
            while j < len(probabilities) and probabilities[j] < threshold:
                silence += step
                j += 1
            if silence >= min_silence_ms or j >= len(probabilities):
                if (i - start_index) * step >= min_speech_ms:
                    spans.append((start_index * step, i * step))
                speaking = False
    if speaking and (len(probabilities) - start_index) * step >= min_speech_ms:
        spans.append((start_index * step, len(probabilities) * step))

    if pad_ms:
        spans = [(max(0, s - pad_ms), min(total_ms, e + pad_ms)) for s, e in spans]
    return spans
