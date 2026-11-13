"""PE-A-Frame(Meta, HF facebook/pe-a-frame-*)으로 말소리 구간을 찾아 기존 TC(SRT)와 비교한다.

정답 TC가 아니라 '기존 TC와의 일치도'를 잰다(정답 SRT를 넣으면 그대로 정확도가 된다).

사용 (GPU PC, 별도 가상환경 권장):
  python -m venv .venv-pea
  .venv-pea\\Scripts\\pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
  .venv-pea\\Scripts\\pip install "transformers>=5.22" soundfile numpy matplotlib
  .venv-pea\\Scripts\\python tools/pea_frame_probe.py --wav voice_only.wav --srt clip_음성만.srt --out pea_out

확인한 사실(2026-11-13, transformers 5.22.2 소스·HF 설정 파일):
- 입력 48kHz 모노, hop 1920샘플 = 프레임 40ms. 위치 한도 10000프레임(약 400초).
- PeAudioFrameLevelModel 출력 logits_audio_text [오디오, 글, 프레임]에 학습된 scale·bias가 이미 곱해짐 → sigmoid = 확률.
- 모델 카드의 spans/threshold 출력은 Meta 별도 패키지(core.audio_visual_encoder)에만 있고 transformers에는 없다 → 구간은 여기서 직접 자른다.
"""
import argparse
import json
import re
from pathlib import Path

import numpy as np


def parse_srt(p):
    tc = lambda h, m, s, ms: int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    pat = r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)"
    r = re.findall(pat, Path(p).read_text(encoding="utf-8-sig"))
    return [(tc(*x[:4]), tc(*x[4:])) for x in r]


def frame_scores(wav_path, model_id, text, chunk_s, dev):
    import soundfile as sf
    import torch
    from transformers import PeAudioFrameLevelModel, PeAudioProcessor

    model = PeAudioFrameLevelModel.from_pretrained(model_id).to(dev).eval()
    proc = PeAudioProcessor.from_pretrained(model_id)
    sr = proc.feature_extractor.sampling_rate
    wav, sr0 = sf.read(wav_path, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(1)
    if sr0 != sr:
        import torchaudio
        wav = torchaudio.functional.resample(torch.from_numpy(wav), sr0, sr).numpy()
    fd = proc.feature_extractor.hop_length / sr
    scores, times = [], []
    for k, s in enumerate(np.arange(0, len(wav) / sr, chunk_s)):
        seg = wav[int(s * sr):int((s + chunk_s) * sr)]
        inp = proc(audio=[seg], text=[text], sampling_rate=sr, return_tensors="pt")
        inp = {a: b.to(dev) if hasattr(b, "to") else b for a, b in inp.items()}
        with torch.no_grad():
            out = model(**inp)
        if k == 0:
            print("출력:", list(out.keys()), tuple(out.logits_audio_text.shape), f"프레임 {fd*1000:.1f}ms")
        sc = torch.sigmoid(out.logits_audio_text[0, 0]).float().cpu().numpy()
        n = int(np.ceil(len(seg) / proc.feature_extractor.hop_length))
        sc = sc[:n]  # 반사 패딩으로 늘어난 끝 프레임 제거
        scores.append(sc)
        times.append(s + np.arange(len(sc)) * fd)
    return np.concatenate(scores), np.concatenate(times), fd


def segments(scores, times, fd, th, min_gap=0.05, min_len=0.1):
    on = scores > th
    segs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j < len(on) and on[j]:
                j += 1
            segs.append([times[i], times[j - 1] + fd])
            i = j
        else:
            i += 1
    m = []
    for s in segs:
        if m and s[0] - m[-1][1] < min_gap:
            m[-1][1] = s[1]
        else:
            m.append(s)
    return [s for s in m if s[1] - s[0] >= min_len]


def compare(ref, segs):
    """자막마다 (인 차이ms, 아웃 차이ms). 앞뒤 자막과 50ms 안으로 붙은 경계는 nan(채점 제외)."""
    st = np.array([s[0] for s in segs]) if segs else np.array([1e9])
    en = np.array([s[1] for s in segs]) if segs else np.array([1e9])
    out = []
    for i, (a, b) in enumerate(ref):
        jin = i > 0 and a - ref[i - 1][1] < 0.05
        jout = i + 1 < len(ref) and ref[i + 1][0] - b < 0.05
        out.append((np.nan if jin else np.abs(st - a).min() * 1000,
                    np.nan if jout else np.abs(en - b).min() * 1000))
    return np.array(out)


def pct(d, w):
    v = d[~np.isnan(d)]
    return float((v <= w).mean() * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--srt", required=True, help="비교할 TC (기존 파형 TC 또는 정답)")
    ap.add_argument("--model", default="facebook/pe-a-frame-small")
    ap.add_argument("--text", default="a person speaking")
    ap.add_argument("--chunk", type=float, default=60.0, help="초. GPU 메모리가 모자라면 30")
    ap.add_argument("--out", default="pea_out")
    ap.add_argument("--scores", help="이미 저장한 scores.npz로 채점만 다시 한다(모델을 돌리지 않음)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    if a.scores:
        z = np.load(a.scores)
        scores, times = z["scores"], z["times"]
        fd = float(times[1] - times[0])
    else:
        import torch
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        print("장치:", dev, torch.cuda.get_device_name(0) if dev == "cuda" else "")
        scores, times, fd = frame_scores(a.wav, a.model, a.text, a.chunk, dev)
        np.savez(out / "scores.npz", scores=scores, times=times)
    ref = parse_srt(a.srt)
    d0 = compare(ref, [[0, 1]])
    print(f"비교 자막 {len(ref)}개, 붙은 경계라 뺀 수 {int(np.isnan(d0).sum())}/{d0.size}")
    print("임계값  구간수  인 중앙값ms  아웃 중앙값ms  ±42ms  ±125ms")
    rows, best = [], None
    for th in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        sg = segments(scores, times, fd, th)
        d = compare(ref, sg)
        r = dict(th=th, n=len(sg), in_med=float(np.nanmedian(d[:, 0])), out_med=float(np.nanmedian(d[:, 1])),
                 w42=pct(d, 42), w125=pct(d, 125))
        rows.append(r)
        print(f"{th:5.1f} {r['n']:6d} {r['in_med']:11.0f} {r['out_med']:13.0f} {r['w42']:5.0f}% {r['w125']:6.0f}%")
        if best is None or r["w125"] > best[0]["w125"]:
            best = (r, sg, d)
    (out / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    r, sg, d = best
    fmt = lambda x: f"{int(x // 60):02d}:{x % 60:06.3f}"
    lines = [f"임계값 {r['th']}", "번호  기존 인      기존 아웃    인 차이ms  아웃 차이ms"]
    lines += [f"{i:3d}  {fmt(x)}  {fmt(y)}  {p:8.0f}  {q:10.0f}" for i, ((x, y), (p, q)) in enumerate(zip(ref, d), 1)]
    (out / "per_cue.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.figure(figsize=(18, 3))
        plt.plot(times, scores, lw=.6)
        plt.axhline(r["th"], c="r")
        for x, y in ref:
            plt.axvspan(x, y, color="g", alpha=.15)
        plt.title("PE-A-Frame prob (blue) vs reference TC (green)")
        plt.savefig(out / "plot.png", dpi=110, bbox_inches="tight")
    except ImportError:
        pass
    print("저장:", out.resolve())


if __name__ == "__main__":
    main()
