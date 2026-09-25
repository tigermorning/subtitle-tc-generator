"""픽셀로 잡은 인점(방송 글자 프레임) 앞뒤 WINDOW_MS 안에 음성 시작점(에너지 급상승)이 있으면 그쪽으로 옮긴다. 시제품.

사용: python audio_snap.py VIDEO IN.srt OUT.srt [미사용] [ONSETS.json]
주의: 탐색창은 100ms가 실측값이다(SE 파란 선 8건). 200ms 이상이면 앞뒤 다른 소리를 잡아 정답에서 멀어진다(HANDOFF_hardsub_tc.md 6-5, 6-6).
"""
import re, subprocess, sys
import numpy as np

video, in_srt, out_srt = sys.argv[1], sys.argv[2], sys.argv[3]
WIN = float(sys.argv[4]) / 1000 if len(sys.argv) > 4 else 0.1
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

BACK_LOOK = 40                           # 시작점 바닥 산정에 보는 앞 구간(200ms)
SOLID, QUIET_RUN, QUIET_X = 40, 10, 2.5  # 발화로 보는 최소 지속 200ms / 바닥 2.5배 미만이 50ms 이어지면 끊긴 것
SKIP = 32                                # 후보 하나를 잡으면 160ms 뒤부터 다음 후보를 찾는다
BACK, FWD = 0.085, 0.11                   # 글자 프레임 앞 85ms ~ 뒤 110ms. 실측 8건에서 앞 -80ms, 뒤 +100ms까지 정답이었고 앞 -100ms, 뒤 +160ms는 정답이 아니었다
FWD_MIN = 0.02                           # 글자 프레임과 20ms 이하 차이는 옮기지 않는다

def sustained(j, floor):
    """j부터 소리가 끊기기(QUIET_RUN hop 연속으로 바닥 QUIET_X배 미만) 전까지의 hop 수. 최대 SOLID까지만 센다."""
    quiet = 0
    for k in range(j, min(j + SOLID + QUIET_RUN, n)):
        quiet = quiet + 1 if env[k] < QUIET_X * floor else 0
        if quiet >= QUIET_RUN:
            return k - QUIET_RUN + 1 - j
    return SOLID

def find_onset(t0):
    """방송 글자가 뜬 프레임(t0) 앞뒤 100ms 안의 음성 시작 후보 중 t0에 가장 가까운 것. 없으면 None(글자 프레임 유지).
    실측(SE 파란 선 8건, 2026-09-25): 글자 프레임 오차 평균 65ms, 이 방식 평균 27ms. 100ms 밖의 소리는 이 자막의 시작이 아니라 앞뒤 소리였다."""
    lo = max(int((t0 - BACK) / (HOP / SR)), PRE)
    hi = min(int((t0 + FWD) / (HOP / SR)) + 20, n - POST)
    best = None
    i = lo - 1
    while i + 1 < hi:
        i += 1
        pre = env[i - PRE:i].min()
        post = env[i:i + POST].mean()
        if post >= RATIO * max(pre, PRE_MIN) and post >= ABS_MIN and env[i + 1:i + 3].mean() > 1.5 * max(pre, PRE_MIN):
            j = i
            while j < hi + 20 and env[j] < 2.0 * max(pre, PRE_MIN):
                j += 1
            t = j * HOP / SR
            floor = max(env[max(j - BACK_LOOK, 0):j].min(), PRE_MIN)
            if t > t0 and sustained(j, floor) < SOLID:      # 글자보다 뒤의 소리는 200ms 이어지는 발화여야 한다(짧은 소리는 정답이 아니었다: 실측 #38)
                i = j + SKIP
                continue
            if -BACK - 1e-9 <= t - t0 <= FWD + 1e-9 and (best is None or abs(t - t0) < abs(best - t0)):
                best = t
            i = j + SKIP
    if best is None or abs(best - t0) <= FWD_MIN:
        return None
    return best

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
