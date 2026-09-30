"""영상 한 구간을 음성(vocals)과 그 외 소리(나머지 합)로 나눈다. 로컬 GPU만 쓴다.

사용: python separate.py VIDEO START_SEC DUR_SEC OUTDIR
모델: torchaudio HDEMUCS_HIGH_MUSDB_PLUS (drums·bass·other·vocals 네 갈래)
- voice.wav  = vocals
- others.wav = 원음 - vocals (배경음악·효과음·환경음)
"""
import os, subprocess, sys
import numpy as np
import torch
import torchaudio
from torchaudio.pipelines import HDEMUCS_HIGH_MUSDB_PLUS as BUNDLE

video, start, dur, outdir = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
SR = BUNDLE.sample_rate  # 44100

# 처음부터 디코딩하고(-ss를 -i 뒤에) 타임스탬프 기준으로 빈 곳을 채운다 — 깨진 프레임이 버려져도 뒤가 당겨지지 않게.
raw = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", video, "-ss", str(start), "-t", str(dur), "-map", "0:a:0",
     "-af", "aresample=async=1:first_pts=0", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
    capture_output=True).stdout
mix = torch.from_numpy(np.frombuffer(raw, np.float32).reshape(-1, 2).T.copy())
print(f"mix {mix.shape[1] / SR:.3f}s (요청 {dur}s)")

model = BUNDLE.get_model().cuda().eval()

# 10초 조각 + 1초 겹침, 겹친 곳은 선형으로 섞는다(torchaudio 튜토리얼 방식).
SEG, OVL = int(10 * SR), int(1 * SR)
ref = mix.mean(0)
norm = (mix - ref.mean()) / ref.std()
L = norm.shape[1]
out = torch.zeros(4, 2, L)
wsum = torch.zeros(L)
fade = torch.linspace(0, 1, OVL)
s = 0
with torch.no_grad():
    while s < L:
        e = min(s + SEG, L)
        chunk = norm[:, s:e].unsqueeze(0).cuda()
        y = model(chunk)[0].cpu()
        w = torch.ones(e - s)
        if s > 0:
            w[:OVL] = fade[: min(OVL, e - s)]
        if e < L:
            w[-OVL:] = torch.minimum(w[-OVL:], fade.flip(0))
        out[:, :, s:e] += y * w
        wsum[s:e] += w
        if e == L:
            break
        s = e - OVL
out = out / wsum.clamp_min(1e-8)
out = out * ref.std() + ref.mean()
vocals = out[model.sources.index("vocals")]
others = mix - vocals

os.makedirs(outdir, exist_ok=True)
from scipy.io import wavfile  # torchaudio.save는 이 PC에 백엔드(soundfile)가 없다

def save(name, x):
    wavfile.write(os.path.join(outdir, name), SR, (x.clamp(-1, 1).T.numpy() * 32767).astype(np.int16))

save("voice.wav", vocals)
save("others.wav", others)
save("mix.wav", mix)
rms = lambda x: float(x.pow(2).mean().sqrt())
print(f"RMS mix {rms(mix):.4f} voice {rms(vocals):.4f} others {rms(others):.4f}")
