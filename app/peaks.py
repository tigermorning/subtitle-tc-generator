"""소리를 파형으로 만든다.

**8kHz로 읽는다.** 그리는 데는 그 이상이 필요 없고, 45분짜리도 40MB 안에 들어온다.
정확도가 필요한 곳(VAD·전사)은 따로 16kHz로 읽으므로 여기서 아낀다.

읽는 동안 화면이 멈추면 안 된다. 그래서 이 모듈은 계산만 하고, 부르는 쪽이 다른
실에서 돌린다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

SAMPLE_RATE = 8000
SAMPLES_PER_PEAK = 128          # 16ms에 점 하나. 40ms 프레임보다 촘촘하다


def load(video: Path, progress=None) -> tuple[list[tuple[float, float]], int, int, int]:
    """(봉우리, 봉우리당 표본 수, 표본율, 길이ms).

    봉우리는 (가장 낮은 값, 가장 높은 값) 쌍이다. 평균을 쓰면 말과 침묵이 뭉개진다 —
    파형은 **크기의 폭**을 봐야 읽힌다.
    """
    import numpy as np

    from checker.media import _as_tool_path, _find

    say = progress or (lambda _m: None)
    say("소리를 읽는 중입니다...")
    result = subprocess.run(
        [_find("ffmpeg"), "-hide_banner", "-nostats", "-v", "error",
         "-i", _as_tool_path(Path(video)), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True, check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return [], SAMPLES_PER_PEAK, SAMPLE_RATE, 0

    samples = np.frombuffer(result.stdout, dtype=np.int16).astype("float32") / 32768.0
    usable = len(samples) - (len(samples) % SAMPLES_PER_PEAK)
    if usable <= 0:
        return [], SAMPLES_PER_PEAK, SAMPLE_RATE, 0

    blocks = samples[:usable].reshape(-1, SAMPLES_PER_PEAK)
    peaks = list(zip(blocks.min(axis=1).tolist(), blocks.max(axis=1).tolist()))
    duration_ms = int(len(samples) / SAMPLE_RATE * 1000)
    say(f"파형 준비 완료 — {duration_ms / 60000:.1f}분")
    return peaks, SAMPLES_PER_PEAK, SAMPLE_RATE, duration_ms
