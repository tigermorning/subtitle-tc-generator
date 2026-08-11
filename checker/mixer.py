"""정답을 아는 오디오를 만든다 — 학습·측정용.

**왜 합성인가**: 말이 정확히 몇 밀리초에 시작하는지는 사람이 라벨링하기 어렵다.
그런데 **섞기 전 트랙을 우리가 쥐고 있으면** 정답이 공짜로 나온다.

    깨끗한 말소리(경계를 아는 것) + 음악·잡음  =  섞인 오디오
                    ↑ 정답은 섞기 전에서 그대로

**순환이 아니다.** 정답이 우리 휴리스틱에서 나오지 않고 **섞는 과정**에서 나온다.
우리가 만든 규칙으로 라벨을 붙이면 모델이 우리 규칙을 배우겠지만, 여기서는 그런
일이 없다.

재료는 사용자의 영상에서 뽑는다. 외부 데이터셋을 받는 것보다 낫다 — 실제로 다룰
소리(그 작품의 음악·잡음·목소리)와 분포가 같기 때문이다. **밖으로 나가지 않는다.**

이 모듈은 학습에도 쓰이지만, 그전에 **재는 데** 쓴다. 검출기가 얼마나 어떻게
틀리는지 알아야 고칠 방법(보정이냐 학습이냐)을 정할 수 있다.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .media import _as_tool_path, _find

SAMPLE_RATE = 16000


@dataclass
class Mixed:
    """섞은 오디오와 그 정답."""
    audio: "object"                      # numpy 배열(float32, 16kHz 모노)
    spans: list[tuple[int, int]]         # 말소리 구간 [(시작ms, 끝ms)]
    snr_db: float


def read_audio(path: Path, start_ms: int = 0, duration_ms: int | None = None):
    """16kHz 모노로 읽는다."""
    import numpy as np

    command = [_find("ffmpeg"), "-hide_banner", "-nostats", "-v", "error"]
    if start_ms:
        command += ["-ss", f"{start_ms / 1000:.3f}"]
    command += ["-i", _as_tool_path(path)]
    if duration_ms:
        command += ["-t", f"{duration_ms / 1000:.3f}"]
    command += ["-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]

    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        return np.zeros(0, dtype="float32")
    return np.frombuffer(result.stdout, dtype=np.int16).astype("float32") / 32768.0


def _rms(samples) -> float:
    import numpy as np

    return float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0


def mix(speech, noise, snr_db: float):
    """말소리에 잡음을 얹는다. 세기는 SNR로 맞춘다.

    **말소리 쪽은 건드리지 않는다.** 잡음 크기만 맞춰서 더한다 — 그래야 정답
    구간이 그대로 유효하다.
    """
    import numpy as np

    if len(noise) == 0:
        return speech.copy()
    # 잡음이 짧으면 이어 붙여 길이를 맞춘다.
    if len(noise) < len(speech):
        noise = np.tile(noise, int(np.ceil(len(speech) / len(noise))))
    noise = noise[:len(speech)]

    speech_rms, noise_rms = _rms(speech), _rms(noise)
    if noise_rms == 0 or speech_rms == 0:
        return speech.copy()
    scale = speech_rms / (noise_rms * (10 ** (snr_db / 20)))
    mixed = speech + noise * scale
    # 넘치면 통째로 줄인다. 잘라내면 없던 왜곡이 생겨 검출기를 속인다.
    peak = float(np.max(np.abs(mixed))) if len(mixed) else 0.0
    return mixed / peak * 0.98 if peak > 0.98 else mixed


def build_clip(speech_clips: list, noise, snr_db: float, gap_ms: int = 700):
    """말소리 토막들을 침묵으로 띄워 늘어놓고 잡음을 얹는다.

    **침묵을 넉넉히 둔다.** 검출기가 경계를 어디로 잡는지 재려면 앞뒤가 조용해야
    한다. 붙여 놓으면 두 말소리가 한 구간으로 뭉쳐 무엇을 쟀는지 알 수 없다.
    """
    import numpy as np

    gap = np.zeros(int(SAMPLE_RATE * gap_ms / 1000), dtype="float32")
    pieces, spans, cursor = [gap], [], len(gap)
    for clip in speech_clips:
        pieces.append(clip)
        start_ms = int(cursor * 1000 / SAMPLE_RATE)
        cursor += len(clip)
        spans.append((start_ms, int(cursor * 1000 / SAMPLE_RATE)))
        pieces.append(gap)
        cursor += len(gap)

    clean = np.concatenate(pieces)
    return Mixed(mix(clean, noise, snr_db), spans, snr_db)


def trim_silence(samples, threshold: float = 0.02, pad_ms: int = 0):
    """토막 앞뒤의 조용한 부분을 잘라낸다.

    말소리 토막을 자막 구간에서 떼어 오면 앞뒤에 여백이 붙는다. 그대로 두면 **정답
    경계가 실제 말 시작보다 앞서** 무엇을 재는지 흐려진다.
    """
    import numpy as np

    if len(samples) == 0:
        return samples
    loud = np.where(np.abs(samples) > threshold)[0]
    if len(loud) == 0:
        return samples[:0]
    pad = int(SAMPLE_RATE * pad_ms / 1000)
    return samples[max(0, loud[0] - pad):min(len(samples), loud[-1] + pad + 1)]
