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

# 확률 열을 구간으로 자르는 값 셋. **2026-08-11 VAD를 들일 때 근거 없이 들어온
# 값이고, 2026-09-08에 처음 실측했다**(`tools/vad_sweep.py` — 확률 열을 한 번만
# 구해 놓고 값만 바꿔 가며 정답 자막의 인점·아웃점과 견준다).
#
#     자료                          지금 값(0.5/120/250)      가장 나았던 값
#     드라마B E02(한국어 드라마)  인 158ms / 아웃 285ms   0.3/80/100 → 136 / 232
#     드라마B E03               인 117ms / 아웃 219ms   0.3/80/100 → 102 / 183
#     영화A(영어 애니 영화)          인 1481ms / 아웃 1487ms 0.7/80/100 → 729 / 675
#
# **방향이 작품마다 뒤집힌다.** 한국어 실사 드라마는 더 느슨한 쪽(0.3)이 낫고,
# 음악이 계속 깔리는 영어 애니메이션은 더 빡빡한 쪽(0.7)이 두 배 낫다. 한 값으로
# 둘 다 맞출 수 없다는 것이 이 실측이 말하는 전부다.
#
# **문턱값은 그래서 안 바꿨다**(규칙 12 — 최소 2편 근거. 여기서 일관되게 가리키는
# 것은 드라마B 한 작품뿐이고, 다른 작품은 반대를 가리킨다). 값을 고치려면
# 같은 성격의 작품이 최소 한 편 더 필요하고, 진짜 답은 아마 **장르·언어별로 다른
# 값**(`rules/genre/`가 하는 일)이지 새 고정값 하나가 아니다.
#
# 구간 수가 함께 늘면 경계가 아무 데나 가까워져 오차가 낮아 보인다는 점도 같이
# 봐야 한다(0.3/80/100은 구간이 20%쯤 많다) — 표에 `구간` 칸이 있는 이유다.
#
# **`MIN_SILENCE_MS`만 250 → 100으로 바꿨다(2026-09-11, 사용자 확인).** 위 세
# 자료가 전부 침묵최소 100을 골랐고, Seoul Corpus(한국어 즉흥 인터뷰 240파일·
# 손보정 경계, `tools/vad_sweep.py --corpus`)로 네 번째가 같은 방향을 가리켰다:
#
#     침묵최소   인점중앙 / 인점95   아웃중앙 / 아웃95   (문턱 0.5 · 말최소 120)
#     100        20ms / 172ms       72ms / 365ms
#     250 (전)   23ms / 2172ms      74ms / 2171ms
#     400        35ms / 7477ms      103ms / 8053ms
#
# 중앙값은 같은데 95%가 열 배 넘게 벌어진다 — 침묵 속 숨·입소리에 확률이 잠깐
# 튀고, 그 조각과 다음 말 사이가 250ms 안 되면 한 구간으로 이어 붙기 때문이다.
# 문턱값은 그대로다(중앙 20~27ms 차이뿐이고 장르 따라 방향이 갈린다).
THRESHOLD = 0.5        # 사람 말일 확률이 이보다 높으면 말하는 중으로 본다
MIN_SPEECH_MS = 120    # 이보다 짧은 소리는 구간으로 세지 않는다
MIN_SILENCE_MS = 100   # 이보다 짧은 침묵으로는 말을 끊지 않는다


class VadUnavailable(Exception):
    """모델이나 실행기가 없다."""


def find_model(explicit: str | None = None) -> Path:
    """`silero_vad.onnx`를 찾는다."""
    import os

    for value in (explicit, os.environ.get("VAD_MODEL")):
        if value and Path(value).is_file():
            return Path(value)
    from .paths import model_dirs

    for folder in model_dirs():
        candidate = folder / "silero_vad.onnx"
        if candidate.is_file():
            return candidate
    raise VadUnavailable(
        "silero_vad.onnx를 찾지 못했습니다. models/ 폴더에 두거나 VAD_MODEL로 "
        "경로를 지정하세요. https://github.com/snakers4/silero-vad 에서 받습니다(2MB).")


# **5.1에서는 센터 채널만 듣는다**(2026-09-12 실측). 대사는 센터(FC)에 있고
# 음악·효과는 나머지 채널에 있다. `-ac 1` 다운믹스는 그 둘을 섞는데, 실측한
# ffmpeg 계수가 하필 대사를 가장 많이 깎는다:
#
#     FC(대사) ×0.293   FL·FR ×0.207   SL·SR ×0.146   (베드 4채널 전력합 ≈0.358)
#
# 즉 다운믹스는 VAD 입력에서 대사를 음악보다 약 1.7dB **아래**로 내려놓는다.
#
# 얼마나 손해였는지 정답 경계를 아는 합성 자료로 쟀다(Seoul Corpus 손라벨
# 15클립 × 180초 + 메이드 인 코리아 E02의 **대사 없는 구간**을 베드로 얹어
# 5.1을 만든 뒤, 같은 파일을 다운믹스와 센터 추출로 각각 읽었다):
#
#     SNR(다운믹스 도메인)   다운믹스 인점중앙/덮음   센터 인점중앙/덮음
#     +15dB                  61ms / 88.2%            39ms / 95.2%
#     +10dB                  87ms / 79.7%            44ms / 92.8%
#      +5dB                 205ms / 68.0%            55ms / 89.2%
#       0dB                1326ms / 41.3%            83ms / 79.4%
#     (말소리만 = 천장       26ms / 97.9%)
#
# 센터 추출이 유효 SNR을 약 10dB 벌어 준다. 실사 2편(정답 SRT 대비, 같은 자):
#
#     메이드 인 코리아 E02  인점중앙 146→137ms  95% 17767→8324ms  덮음 83.0→86.9%
#     토이스토리5          인점중앙 889→776ms  95% 17032→11752ms 덮음 83.3→87.3%
#
# **중앙값 이득은 작고 꼬리·덮음에서 크다** — 대사는 대부분 음악보다 충분히
# 크게 믹스돼 있어서, 이 고침이 값을 내는 자리는 음악이 큰 장면이다. 발주처·
# 장르가 다른 2편이 같은 방향이라 규칙 12를 채운다.
#
# 대사가 센터에 있다는 것도 추측이 아니라 실측이다 — E02에서 Silero가 말로
# 잡은 시간이 센터 28.3%, 나머지 채널 0.2%였다. 그래도 믹스가 다르면 센터가
# 빌 수 있으므로 아래 `CENTER_MIN_RMS_RATIO`로 확인하고 되돌린다.
CENTER_MIN_RMS_RATIO = 0.1


def _decode(video: Path, audio_filter: str | None = None):
    """16kHz 모노 PCM으로 읽는다. ffmpeg이 이미 있으니 그것을 쓴다."""
    import numpy as np

    command = [_find("ffmpeg"), "-hide_banner", "-nostats", "-v", "error",
               "-i", _as_tool_path(video), "-vn"]
    command += ["-af", audio_filter] if audio_filter else ["-ac", "1"]
    command += ["-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        detail = (result.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise MediaToolUnavailable(f"오디오를 읽지 못했습니다: {detail}")
    return np.frombuffer(result.stdout, dtype=np.int16).astype("float32") / 32768.0


def _layout_has_center(csv_text: str) -> bool:
    """`ffprobe ... -of csv=p=0`이 낸 `채널수,레이아웃` 한 줄을 읽는다.

    파싱을 따로 뗀 이유는 시험이 ffprobe 없이 확인할 수 있어야 하기 때문이다.
    레이아웃 이름이 없을 때(`unknown`)는 채널 수로 판단한다 — 3채널 이상이면
    센터가 있다고 본다.
    """
    text = (csv_text or "").strip()
    if not text:
        return False
    head = text.splitlines()[0]
    parts = [x.strip().lower() for x in head.split(",")]
    channels = parts[0] if parts else ""
    layout = parts[1] if len(parts) > 1 else ""
    if layout and layout != "unknown":
        # 5.1·5.1(side)·7.1·3.0 … 모두 센터를 가진다. 스테레오·모노는 없다.
        return layout not in ("mono", "stereo", "downmix") and not layout.startswith("2.")
    return channels.isdigit() and int(channels) >= 3


def _has_center(video: Path) -> bool:
    """첫 오디오 스트림에 센터 채널이 있나. 없으면 다운믹스로 간다."""
    try:
        result = subprocess.run(
            [_find("ffprobe"), "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=channels,channel_layout",
             "-of", "csv=p=0", _as_tool_path(video)],
            capture_output=True, check=False)
    except MediaToolUnavailable:
        return False
    return _layout_has_center((result.stdout or b"").decode("utf-8", "replace"))


def _center_is_empty(center_rms: float, downmix_rms: float) -> bool:
    """센터가 비었나 — 대사를 센터에 두지 않은 믹스를 걸러 낸다."""
    return downmix_rms > 0 and center_rms < CENTER_MIN_RMS_RATIO * downmix_rms


def _read_audio(video: Path, source: str = "auto", progress=None):
    """VAD에 먹일 16kHz 모노. `source`는 auto | center | downmix.

    `auto`는 센터 채널이 있으면 센터만 쓰고, 센터가 비어 있으면(대사를 다른
    채널에 둔 믹스) 다운믹스로 되돌린다. 어느 쪽을 썼는지 **말한다** — 조용히
    고르면 나중에 결과가 달라졌을 때 원인을 못 찾는다(규칙 4).
    """
    import numpy as np

    say = progress or (lambda _m: None)
    video = Path(video)
    if source == "downmix" or (source == "auto" and not _has_center(video)):
        return _decode(video)
    center = _decode(video, "pan=mono|c0=FC")
    if source == "center":
        return center
    downmix = _decode(video)
    center_rms = float(np.sqrt(np.mean(center ** 2))) if len(center) else 0.0
    downmix_rms = float(np.sqrt(np.mean(downmix ** 2))) if len(downmix) else 0.0
    if _center_is_empty(center_rms, downmix_rms):
        say("센터 채널이 거의 비어 있어 다운믹스로 듣습니다")
        return downmix
    say("5.1 센터 채널(대사)만 듣습니다 — 음악·효과는 빼고 봅니다")
    return center


def detect_speech(video: Path, threshold: float = THRESHOLD,
                  min_speech_ms: int = MIN_SPEECH_MS,
                  min_silence_ms: int = MIN_SILENCE_MS,
                  pad_ms: int = 0, model: str | None = None,
                  progress=None, audio_source: str = "auto") -> list[tuple[int, int]]:
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
    audio = _read_audio(Path(video), audio_source, say)
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
