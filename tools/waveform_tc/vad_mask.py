"""분리한 음성에서 사람 말소리가 아닌 자리를 0으로 지운다(Silero VAD, onnxruntime).

사용: python vad_mask.py VOICE.wav OUT.wav [문턱 0.5] [여유초 0.3] [KEEP.json]
말소리 판정 구간 앞뒤로 여유를 두어 작게 시작·끝나는 소리는 남긴다.
경계 자리(인점·아웃점)는 이 파일이 아니라 다음 단계(wave_tc.py)가 파형으로 잡는다.
"""
import sys, wave
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from checker.vad import _probabilities, find_model, SAMPLE_RATE, WINDOW  # noqa: E402

src, dst = sys.argv[1], sys.argv[2]
thr = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
pad = float(sys.argv[4]) if len(sys.argv) > 4 else 0.3

with wave.open(src) as w:
    sr, ch = w.getframerate(), w.getnchannels()
    raw = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, ch)
mono = raw.mean(1).astype(np.float32) / 32768
# 16kHz로 줄여 VAD에 넣는다(선형 보간이면 판정용으로 충분)
t16 = np.arange(0, len(mono) / sr, 1 / SAMPLE_RATE)
a16 = np.interp(t16, np.arange(len(mono)) / sr, mono).astype(np.float32)
prob = np.asarray(_probabilities(a16, find_model()))
step = WINDOW / SAMPLE_RATE  # 32ms

keep = np.zeros(len(mono), bool)
for k in np.flatnonzero(prob >= thr):
    a = max(0, int((k * step - pad) * sr)); b = min(len(mono), int(((k + 1) * step + pad) * sr))
    keep[a:b] = True
if len(sys.argv) > 5:  # 대본이 있는데 VAD가 놓친 자리(외침·아이·기계 목소리) — 대본 시각 ±0.3초를 되살린다
    import json
    for a, b in json.load(open(sys.argv[5], encoding="utf-8")):
        keep[max(0, int((a - 0.3) * sr)):min(len(mono), int((b + 0.3) * sr))] = True
out = raw.copy(); out[~keep] = 0
with wave.open(dst, "wb") as w:
    w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr); w.writeframes(out.tobytes())
print(f"말소리 판정 {keep.mean() * 100:.1f}% 남김 (문턱 {thr}, 여유 {pad}s)")
