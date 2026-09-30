"""분리한 음성 트랙(voice.wav)만으로 TC를 잡는다. 시제품.

사용: python voice_tc.py VOICE.wav OFFSET_SEC OUTDIR
1. Silero VAD(faster-whisper 동봉 v6)로 말소리 구간을 대강 잡는다 — 32ms 단위라 경계가 거칠다
2. 파형 포락선(10ms 창, 5ms 간격, dBFS)으로 경계를 다시 잡는다
   - 인점: VAD 시작 앞뒤에서 바닥보다 ON_DB 이상 올라가 20ms 이어지는 첫 지점
   - 아웃점: VAD 끝 앞뒤에서 바닥보다 OFF_DB 이상인 마지막 지점
3. 자막 단위로 묶고 넷플릭스 시간 규칙을 건다(최소 5/6초, 최대 7초, 0.5초 미만 간격은 2프레임으로 붙임, 29.97fps 프레임에 맞춤)
   장면전환 규칙은 영상이 필요해서 여기서는 걸지 않는다.
4. 텍스트는 같은 음성 트랙을 로컬 faster-whisper로 받아 적어 채운다(참고용).

출력: voice_raw.srt(2단계까지, 규칙 없음), voice_tc.srt(3·4단계까지), cues.json
"""
import json, os, sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
from faster_whisper.vad import VadOptions, get_speech_timestamps

path, OFFSET, outdir = sys.argv[1], float(sys.argv[2]), sys.argv[3]
SR, HOP = 16000, 80                     # 5ms
FPS = 30000 / 1001
FRAME = 1 / FPS

sr0, x = wavfile.read(path)
x = x.astype(np.float32) / 32768
if x.ndim == 2:
    x = x.mean(1)
a = resample_poly(x, 160, 441).astype(np.float32) if sr0 == 44100 else x
dur = len(a) / SR

# 1. VAD
vad = get_speech_timestamps(a, VadOptions(threshold=0.5, min_speech_duration_ms=120,
                                          min_silence_duration_ms=200, speech_pad_ms=0))
segs = [(v["start"] / SR, v["end"] / SR) for v in vad]
print(f"audio {dur:.2f}s, VAD 구간 {len(segs)}")

# 2. 파형 포락선
n = len(a) // HOP
sq = (a[: n * HOP] ** 2).reshape(n, HOP).mean(1)
env = 10 * np.log10(np.convolve(sq, np.ones(2) / 2, "same") + 1e-10)   # dBFS
ABS_MIN = -50.0          # 분리 트랙의 빈자리는 -60dB 아래로 떨어진다. 이보다 작은 소리는 말로 보지 않는다
ON_DB, OFF_DB = 12.0, 10.0
SEARCH_BACK, SEARCH_FWD = 0.15, 0.15     # VAD 경계 앞뒤 탐색 폭
hop_t = HOP / SR

def floor_db(i0, i1):
    seg = env[max(i0, 0):max(min(i1, n), 1)]
    return float(np.percentile(seg, 20)) if len(seg) else -80.0

def onset(t, fwd=SEARCH_FWD):
    lo, hi = max(int((t - SEARCH_BACK) / hop_t), 0), min(int((t + fwd) / hop_t), n - 4)
    thr = max(floor_db(lo - 60, lo) + ON_DB, ABS_MIN)            # 앞 300ms 바닥
    for k in range(lo, hi):
        if env[k] >= thr and env[k:k + 4].mean() >= thr:
            return k * hop_t
    return t

def offset(t, nxt):
    lo = max(int((t - SEARCH_BACK) / hop_t), 0)
    hi = min(int((t + 0.3) / hop_t), n - 1, int(nxt / hop_t))
    thr = max(floor_db(hi, hi + 60) + OFF_DB, ABS_MIN)            # 뒤 300ms 바닥
    last = None
    for k in range(lo, hi):
        if env[k] >= thr:
            last = k
    return (last + 1) * hop_t if last is not None else t

# 텍스트(참고용)와 낱말 경계: 로컬 faster-whisper. 낱말 시각은 거칠어서 경계 위치는 파형이 정하고, 낱말은 '여기가 낱말 사이인가'만 본다
from faster_whisper import WhisperModel
model = WhisperModel("mobiuslabsgmbh/faster-whisper-large-v3-turbo", device="cuda", compute_type="float16")
seg_iter, _ = model.transcribe(a, language="ko", word_timestamps=True, vad_filter=False, beam_size=5,
                               condition_on_previous_text=False)
words = [w for s in seg_iter for w in (s.words or [])]

# 1-1. VAD가 놓친 말을 낱말로 되살린다. 실측: 충격음이 섞인 자리의 말(174.9초·200.7초)은 VAD 확률이 낮았지만
# 음성 트랙에 소리가 있었고 whisper도 낱말을 냈다. 낱말이 VAD 구간 밖이고 파형도 ABS_MIN 이상이면 구간으로 넣는다
RESCUE_MARGIN = 0.6                      # 낱말 시각은 수백 ms씩 어긋난다. VAD 구간 바로 옆 낱말은 이미 그 구간의 말이다
covered = lambda t: any(s0 - RESCUE_MARGIN <= t <= e0 + RESCUE_MARGIN for s0, e0 in segs)
rescued = []
for w in words:
    mid = (w.start + w.end) / 2
    if covered(mid) or env[int(w.start / hop_t):max(int(w.end / hop_t), int(w.start / hop_t) + 1)].max() < ABS_MIN:
        continue
    if rescued and w.start - rescued[-1][1] < 0.5:
        rescued[-1][1] = w.end
    else:
        rescued.append([w.start, w.end])
merged = []
for s0, e0 in sorted(segs + [tuple(r) for r in rescued]):
    if merged and s0 <= merged[-1][1]:
        merged[-1][1] = max(merged[-1][1], e0)
    else:
        merged.append([s0, e0])
segs = [tuple(m) for m in merged]
rescued_starts = [r[0] for r in rescued]
print(f"낱말로 되살린 구간 {len(rescued)}: {[round(r[0] + OFFSET, 2) for r in rescued]}")

raw = []
for j, (s, e) in enumerate(segs):
    nxt = segs[j + 1][0] if j + 1 < len(segs) else dur
    on = onset(s, 0.5 if any(abs(s - r) < 1e-6 for r in rescued_starts) else SEARCH_FWD)   # 되살린 구간은 낱말 시각이 거칠어 뒤로 더 본다
    off = offset(e, nxt)
    if off - on >= 0.08:
        raw.append([on, off, s, e])

def fmt(t):
    ms = int(round(t * 1000))
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"

def write(name, cues, key_text=None):
    with open(os.path.join(outdir, name), "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            text = c[key_text] if key_text else "(음성)"
            f.write(f"{i}\n{fmt(c['in'] + OFFSET)} --> {fmt(c['out'] + OFFSET)}\n{text}\n\n")

write("voice_raw.srt", [{"in": r[0], "out": r[1]} for r in raw])

# 3-0. 구간 안의 짧은 끊김(골짜기). VAD는 200ms 미만 쉼을 못 가른다. 실측: 구 사이 끊김은 40~80ms, 앞뒤보다 15~20dB 낮다
DIP_DB, DIP_MIN, PEAK_WIN = 12.0, 3, 60          # 12dB, 15ms, 앞뒤 300ms
WORD_TOL = 0.12                                   # 낱말 시작과 120ms 안이면 낱말 사이로 본다
word_starts = np.array([w.start for w in words] or [-9.0])
def dips_in(on, off):
    i0, i1 = int(on / hop_t), int(off / hop_t)
    out, k = [], i0 + 20
    while k < i1 - 20:
        pk = min(env[max(k - PEAK_WIN, i0):k].max(), env[k:min(k + PEAK_WIN, i1)].max())
        if env[k] < pk - DIP_DB:
            j = k
            while j < i1 and env[j] < pk - DIP_DB:
                j += 1
            if j - k >= DIP_MIN:
                t = onset(j * hop_t - 0.02)                 # 골짜기 뒤 첫 소리 시작
                depth = pk - env[k:j].min()
                if np.abs(word_starts - t).min() <= WORD_TOL:
                    out.append((t, depth, k * hop_t, j - k))
            k = j + 1
        else:
            k += 1
    return out

# 3. 자막 단위로 묶기
MERGE_GAP, MAX_DUR, MIN_DUR = 0.30, 7.0, 5 / 6
cues = []
for on, off, *_ in raw:
    if cues and on - cues[-1]["out"] < MERGE_GAP and off - cues[-1]["in"] <= MAX_DUR:
        cues[-1]["out"] = off
    else:
        cues.append({"in": on, "out": off})

# 3-1. 골짜기에서 가른다: MAX_PIECE보다 긴 자막만, 가장 오래 끊긴 골짜기부터. 양쪽 모두 MIN_PIECE 이상 남아야 한다
# (첫 골짜기에서 바로 자르면 구가 아닌 자리에서 끊겼다 — 1차 실측 131.2초·136.1초)
MIN_PIECE, MAX_PIECE = 1.0, 2.5
def split(c):
    if c["out"] - c["in"] <= MAX_PIECE:
        return [c]
    ok = [d for d in dips_in(c["in"], c["out"]) if d[0] - c["in"] >= MIN_PIECE and c["out"] - d[0] >= MIN_PIECE]
    if not ok:
        return [c]
    t, depth, dip_t, width = max(ok, key=lambda d: (d[3], d[1]))
    return split({"in": c["in"], "out": dip_t}) + split({"in": t, "out": c["out"]})
cues = [p for c in cues for p in split(c)]

# 7초 넘는 구간은 가운데 1/4~3/4에서 포락선이 가장 낮은 곳에서 가른다(한 번 이상 필요하면 반복)
changed = True
while changed:
    changed = False
    for idx, c in enumerate(cues):
        if c["out"] - c["in"] > MAX_DUR:
            lo = int((c["in"] + (c["out"] - c["in"]) / 4) / hop_t)
            hi = int((c["in"] + 3 * (c["out"] - c["in"]) / 4) / hop_t)
            k = lo + int(np.argmin(np.convolve(env[lo:hi], np.ones(10) / 10, "same")))
            cues[idx:idx + 1] = [{"in": c["in"], "out": k * hop_t}, {"in": k * hop_t + 2 * FRAME, "out": c["out"]}]
            changed = True
            break

# 프레임에 맞춤: 절대 시각 기준. 인점은 소리가 걸친 프레임 시작, 아웃점은 소리가 끝난 뒤 첫 프레임 경계
def snap_in(t):
    return np.floor((t + OFFSET) / FRAME + 1e-6) * FRAME - OFFSET

def snap_out(t):
    return np.ceil((t + OFFSET) / FRAME - 1e-6) * FRAME - OFFSET

for c in cues:
    c["voice_in"], c["voice_out"] = c["in"], c["out"]
    c["in"], c["out"] = snap_in(c["in"]), snap_out(c["out"])

# 최소 노출, 간격 규칙
GAP2 = 2 * FRAME
for i, c in enumerate(cues):
    nxt = cues[i + 1]["in"] if i + 1 < len(cues) else dur
    if c["out"] - c["in"] < MIN_DUR:
        c["out"] = min(c["in"] + np.ceil(MIN_DUR / FRAME - 1e-6) * FRAME, nxt - GAP2)
    gap = nxt - c["out"]
    if i + 1 < len(cues) and gap < 0.5:
        c["out"] = nxt - GAP2          # 0.5초 미만 간격은 2프레임으로 붙인다

for c in cues:
    c["words"] = []
orphan = []
for w in words:
    mid = w.end - 0.05                  # whisper 낱말 시각은 앞당겨진다. 가운데로 배정하면 경계의 낱말이 앞 자막으로 갔다
    best, bd = None, 1e9
    for c in cues:
        d = 0 if c["voice_in"] - 0.2 <= mid <= c["voice_out"] + 0.2 else min(abs(mid - c["voice_in"]), abs(mid - c["voice_out"]))
        if d < bd:
            best, bd = c, d
    if best is not None and bd <= 0.5:
        best["words"].append(w.word)
    else:
        orphan.append((round(w.start + OFFSET, 2), w.word))
for c in cues:
    c["text"] = "".join(c["words"]).strip() or "(인식 안 됨)"

write("voice_tc.srt", cues, "text")
json.dump([{"in": round(c["in"] + OFFSET, 3), "out": round(c["out"] + OFFSET, 3),
            "voice_in": round(c["voice_in"] + OFFSET, 3), "voice_out": round(c["voice_out"] + OFFSET, 3),
            "text": c["text"]} for c in cues],
          open(os.path.join(outdir, "cues.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"raw {len(raw)}, 자막 {len(cues)}, 인식된 낱말 {len(words)}, 자막 밖 낱말 {len(orphan)}")
for o in orphan:
    print("  자막 밖:", o)
