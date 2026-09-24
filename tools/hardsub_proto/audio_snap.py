"""픽셀로 잡은 인점을 음성 시작점(에너지 급상승)으로 당기거나 미룬다. 시제품.

사용: python audio_snap.py VIDEO IN.srt OUT.srt [WINDOW_MS=200] [ONSETS.json]
주의: 탐색창은 200ms가 검증된 값이다. 500ms로 넓히면 앞뒤 다른 소리를 잡아 결과가 흔들린다(HANDOFF_hardsub_tc.md).
기준(사용자 확인): SE 파형에서 파란 선이 맞는 선 = 소리가 처음 올라오는 지점.
"""
import re, subprocess, sys
import numpy as np

video, in_srt, out_srt = sys.argv[1], sys.argv[2], sys.argv[3]
WIN = float(sys.argv[4]) / 1000 if len(sys.argv) > 4 else 0.2
SR, HOP = 16000, 80                      # 5ms
PRE, POST = 10, 5                        # 앞 50ms 최저값 / 뒤 25ms 평균
RATIO, ABS_MIN, PRE_MIN = 4.0, 900.0, 100.0

raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", str(SR),
                      "-f", "s16le", "-"], capture_output=True).stdout
a = np.frombuffer(raw, np.int16).astype(np.float32)
n = len(a) // HOP
sq = (a[: n * HOP] ** 2).reshape(n, HOP).mean(1)
env = np.sqrt(np.convolve(sq, np.ones(2) / 2, "same"))      # 10ms 창, 5ms 간격
print(f"audio {len(a)/SR:.1f}s, {n} hops")

def find_onset(t0):
    lo = max(int((t0 - WIN) / (HOP / SR)), PRE)
    hi = min(int((t0 + WIN) / (HOP / SR)), n - POST)
    for i in range(lo, hi):
        pre = env[i - PRE:i].min()
        post = env[i:i + POST].mean()
        if post >= RATIO * max(pre, PRE_MIN) and post >= ABS_MIN and env[i + 1:i + 3].mean() > 1.5 * max(pre, PRE_MIN):
            # 실제 올라오는 첫 hop까지 앞으로 당겨 붙인다 (평균 창이 조금 일찍 걸리므로)
            j = i
            while j < hi and env[j] < 2.0 * max(pre, PRE_MIN):
                j += 1
            return j * HOP / SR
    return None

def parse(ts):
    h, m, s, ms = map(int, re.findall(r"\d+", ts))
    return h * 3600 + m * 60 + s + ms / 1000

def fmt(t):
    ms = int(t * 1000)
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"

blocks = open(in_srt, encoding="utf-8").read().strip().split("\n\n")
out, shifts, miss = [], [], 0
for b in blocks:
    L = b.split("\n")
    st, en = [parse(x) for x in L[1].split(" --> ")]
    on = None if L[2].startswith("[읽기 실패]") else find_onset(st)
    if on is None:
        miss += 1
    else:
        shifts.append((int(L[0]), st, on, (on - st) * 1000))
        if on < en - 0.15:
            st = on
    out.append(f"{L[0]}\n{fmt(st)} --> {fmt(en)}\n" + "\n".join(L[2:]))
open(out_srt, "w", encoding="utf-8").write("\n\n".join(out) + "\n")

d = np.array([s[3] for s in shifts])
print(f"cues {len(blocks)}, 음성 시작 찾음 {len(shifts)}, 못 찾음(픽셀 시각 유지) {miss}")
print(f"이동량(ms) 중앙 {np.median(d):.0f}, 평균절대 {np.abs(d).mean():.0f}, 5~95% {np.percentile(d,5):.0f}~{np.percentile(d,95):.0f}")
for lo, hi in ((-200, -100), (-100, -30), (-30, 30), (30, 100), (100, 200)):
    print(f"  {lo:5d}~{hi:4d}ms: {int(((d>=lo)&(d<hi)).sum())}")
for k in (28, 29):
    for s in shifts:
        if s[0] == k:
            print(f"cue {k}: 픽셀 {s[1]:.3f} -> 음성 {s[2]:.3f} ({s[3]:+.0f}ms)")

import json as _json
_json.dump([[s[0], round(s[1] * 1000), round(s[2] * 1000)] for s in shifts], open(sys.argv[5] if len(sys.argv) > 5 else "onsets.json", "w"))
