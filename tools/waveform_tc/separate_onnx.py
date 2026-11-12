"""MDX-Net ONNX(Kim_Vocal_2)로 사람 음성만 분리한다. torch 없이 numpy+onnxruntime(CPU).

사용: python separate_onnx.py MODEL.onnx MIX.wav OUT_VOICE.wav
입력은 44.1kHz 스테레오 wav. 모델 설정(UVR 공개 값): n_fft 7680, hop 1024, dim_f 3072, dim_t 256.
"""
import sys, wave
import numpy as np
import onnxruntime as ort

model, src, dst = sys.argv[1:4]
N_FFT, HOP, DIM_F, DIM_T = 7680, 1024, 3072, 256
CHUNK = HOP * (DIM_T - 1)
TRIM = N_FFT // 2
WIN = np.hanning(N_FFT + 1)[:-1].astype(np.float32)

with wave.open(src) as w:
    sr, ch = w.getframerate(), w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, ch).T.astype(np.float32) / 32768
assert sr == 44100 and ch == 2, (sr, ch)


def stft(sig):  # sig: (2, CHUNK + 2*TRIM) -> (4, DIM_F, DIM_T)
    p = np.pad(sig, ((0, 0), (N_FFT // 2, N_FFT // 2)), mode="reflect")
    idx = np.arange(DIM_T)[:, None] * HOP + np.arange(N_FFT)[None]
    spec = np.fft.rfft(p[:, idx] * WIN, axis=-1)  # (2, T, F)
    spec = spec.transpose(0, 2, 1)[:, :DIM_F]  # (2, F, T)
    return np.concatenate([spec.real, spec.imag], 0).astype(np.float32)


def istft(m):  # (4, DIM_F, DIM_T) -> (2, len)
    spec = m[:2] + 1j * m[2:]
    spec = np.pad(spec, ((0, 0), (0, N_FFT // 2 + 1 - DIM_F), (0, 0)))
    frames = np.fft.irfft(spec.transpose(0, 2, 1), n=N_FFT, axis=-1) * WIN  # (2, T, N)
    L = HOP * (DIM_T - 1) + N_FFT
    out, norm = np.zeros((2, L), np.float32), np.zeros(L, np.float32)
    for t in range(DIM_T):
        out[:, t * HOP:t * HOP + N_FFT] += frames[:, t]
        norm[t * HOP:t * HOP + N_FFT] += WIN ** 2
    out /= np.maximum(norm, 1e-8)
    return out[:, N_FFT // 2:N_FFT // 2 + HOP * (DIM_T - 1)]


sess = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
gen = CHUNK - 2 * TRIM  # 조각마다 앞뒤 TRIM을 버리고 가운데만 쓴다
n = x.shape[1]
pad_r = gen - n % gen
xp = np.pad(x, ((0, 0), (TRIM, TRIM + pad_r)))
out = np.zeros((2, n + pad_r), np.float32)
for i in range(0, n + pad_r, gen):
    seg = xp[:, i:i + CHUNK]
    if seg.shape[1] < CHUNK:
        seg = np.pad(seg, ((0, 0), (0, CHUNK - seg.shape[1])))
    pred = sess.run(None, {"input": stft(seg)[None]})[0][0]
    out[:, i:i + gen] = istft(pred)[:, TRIM:TRIM + gen]
    print(f"\r{min(i + gen, n) / sr:6.1f}s / {n / sr:.1f}s", end="", flush=True)
voice = out[:, :n]
print()
with wave.open(dst, "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((np.clip(voice, -1, 1).T * 32767).astype(np.int16).tobytes())
print("voice rms", float(np.sqrt((voice ** 2).mean())), "mix rms", float(np.sqrt((x ** 2).mean())))
