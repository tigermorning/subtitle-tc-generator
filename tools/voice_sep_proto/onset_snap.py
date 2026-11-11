"""하드섭 초안(fix7)의 인점만 음성 트랙의 소리 오름으로 보정한다. 아웃점·텍스트·분할은 건드리지 않는다.

사용: python onset_snap.py VOICE.wav OFFSET_SEC FIX7_FINAL.srt START END OUT_SRT OUT_REPORT_JSON
  - OFFSET_SEC: voice.wav 0초가 영상의 몇 초인지
  - START, END: 영상 시각 구간(초). 인점이 이 안에 있는 큐만 낸다
  - 선택 8번째 인자 SHOTS.json: 장면전환 ms 목록. 있으면 보정 뒤 인점에 전환 규칙을 건다
근거: HANDOFF_voice_sep_tc.md 8~10절. 인점 = 소리가 오르는 자리(-10ms 안팎).
믿는 조건: 앞 300ms가 조용하고(ABS_MIN 미만 또는 오름이 바닥보다 ON_DB 이상) 오름이 탐색 창 안에 있을 때만.
그 밖에는 화면 글자 인점을 그대로 두고 'unreadable'로 표시한다(음악·연속 발화는 사람이 본다).
"""
import json, re, sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

wav, OFFSET, src, T0, T1, out_srt, out_rep = (sys.argv[1], float(sys.argv[2]), sys.argv[3],
                                              float(sys.argv[4]), float(sys.argv[5]), sys.argv[6], sys.argv[7])
import math
SHOTS = json.load(open(sys.argv[8])) if len(sys.argv) > 8 else []
SR, HOP = 16000, 80
FPS = 30000 / 1001
hop_t = HOP / SR
ABS_MIN, ON_DB = -50.0, 12.0
WIN_BACK, WIN_FWD = 0.30, 0.30          # 화면 글자 인점 앞뒤 탐색 폭
MAX_SNAP = 0.12                         # 화면 글자와 이보다 먼 오름은 앞·뒤 말의 오름일 수 있어 보정하지 않고 far로 표시한다
QUIET_DB = -45.0                        # 앞 쪽 조용함의 기준: 앞 200ms 최대가 이보다 작으면 조용한 앞

sr0, x = wavfile.read(wav)
x = x.astype(np.float32) / 32768
if x.ndim == 2:
    x = x.mean(1)
a = resample_poly(x, 160, 441).astype(np.float32) if sr0 == 44100 else x
n = len(a) // HOP
sq = (a[: n * HOP] ** 2).reshape(n, HOP).mean(1)
env = 10 * np.log10(np.convolve(sq, np.ones(2) / 2, "same") + 1e-10)


def ts(s):
    h, m, r = s.split(":")
    sec, ms = r.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def fmt(t):
    f = round(t * FPS)                      # 프레임 정수로 맞춘 뒤 ms로 적는다
    ms = round(f / FPS * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


cues = []
for b in open(src, encoding="utf-8-sig").read().strip().split("\n\n"):
    l = b.split("\n")
    s, e = (ts(p) for p in l[1].split(" --> "))
    if T0 <= s <= T1:
        cues.append([s, e, "\n".join(l[2:])])


def find_onset(t_screen):
    """화면 글자 인점 t_screen(영상 시각) 근처의 소리 오름을 찾는다. (시각, 상태) 반환"""
    t = t_screen - OFFSET
    lo, hi = max(int((t - WIN_BACK) / hop_t), 0), min(int((t + WIN_FWD) / hop_t), n - 4)
    if lo >= hi:
        return None, "out_of_range"
    pre = env[max(lo - 40, 0):lo + 1]                    # 창 앞 200ms
    quiet_start = pre.max() < QUIET_DB if len(pre) else False
    base = float(np.percentile(env[max(lo - 60, 0):lo + 1], 20)) if lo > 0 else -80.0
    thr = max(base + ON_DB, ABS_MIN)
    for k in range(lo, hi):
        if env[k] >= thr and env[k:k + 4].mean() >= thr:
            # 창 맨 앞에서 이미 올라 있으면 앞말에서 이어진 소리 -> 오름이 아니다
            if k == lo and env[lo] >= thr:
                return None, "continuous"
            return k * hop_t + OFFSET, "ok" if quiet_start or env[max(k - 20, 0):k].max() < thr else "weak"
    return None, "no_onset"


rows, out = [], []
for i, (s, e, text) in enumerate(cues, 1):
    on, status = find_onset(s)
    new_s = s
    if on is not None and status == "ok" and abs(on - s) > MAX_SNAP:
        status = "far"
    if on is not None and status == "ok":
        new_s = on
    # 작업 기본 원칙: 전환 앞뒤 0.5초 안의 인점은 전환 프레임에 딱 붙인다(소리 오름보다 우선)
    attached = None
    near = [sh / 1000 for sh in SHOTS if 0 < abs(new_s - sh / 1000) < 0.5 and abs(new_s - sh / 1000) > 0.5 / FPS]
    if near:
        attached = min(near, key=lambda v: abs(v - new_s))
        new_s = math.ceil(round(attached * FPS) / FPS * 1000) / 1000
    rows.append({"attached_to_shot": None if attached is None else round(attached, 3), "n": i, "screen_in": round(s, 3), "voice_onset": None if on is None else round(on, 3),
                 "status": status, "new_in": round(new_s, 3), "out": round(e, 3), "delta_ms": round((new_s - s) * 1000)})
    out.append((new_s, e, text))

with open(out_srt, "w", encoding="utf-8") as f:
    for i, (s, e, text) in enumerate(out, 1):
        f.write(f"{i}\n{fmt(s)} --> {fmt(e)}\n{text}\n\n")
json.dump(rows, open(out_rep, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
from collections import Counter
print("큐", len(rows), dict(Counter(r["status"] for r in rows)))
d = [r["delta_ms"] for r in rows if r["status"] == "ok"]
if d:
    print("보정량(ms) 중앙값", int(np.median(d)), "범위", min(d), max(d))
