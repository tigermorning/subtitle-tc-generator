"""하드섭 초안의 인점·아웃점을 음성 트랙과 규정만으로 다시 정한다. 큐 자리(분할)와 텍스트는 fix7에서 빌린다.

사용: python voice_tc_draft.py VOICE.wav OFFSET_SEC FIX7_FINAL.srt START END SHOTS.json OUT_SRT OUT_REPORT_JSON
- 인점 = 소리 오름(앞이 조용하고 화면 글자 인점 ±0.3초 안). 2~3프레임 전이 아니다(사용자 교정 3개 구간 중앙값 0~-10ms)
- 아웃점 = 마지막 소리 덩어리 끝 + 9프레임(사용자 교정 06~08분 9건 6.9~11.2f, 중앙 9.2f). 0.15초보다 짧은 꼬리 소리는 말로 보지 않고,
  0.7초보다 짧은 쉼은 한 덩어리로 본다
- 앞뒤 큐가 150ms 안으로 붙은 경계는 말 중간 분할(뜻 단위)이라 음성으로 못 정한다. fix7 값을 그대로 둔다
- 장면전환(작업 기본 원칙 373~374행, 넷플릭스·디즈니): 인점은 전환 앞뒤 0.5초 안이면 전환 프레임에 붙인다.
  아웃점은 전환 -2프레임이거나 0.5초(15프레임) 이상. 아웃점은 말이 끝난 뒤로 늘리는 후보를 쓰지 않는다
- 최소 길이 25프레임, 겹침은 다음 인점 우선(2프레임 띄움)
- 판독이 안 되는 곳(오름 없음·앞말에 이어짐·끝 없음)은 fix7 값을 두고 report의 notes에 남긴다. 사람이 SE에서 본다
"""
import json, math, sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

wav, OFFSET, src, T0, T1, shots_p, out_srt, out_rep = (sys.argv[1], float(sys.argv[2]), sys.argv[3], float(sys.argv[4]),
                                                      float(sys.argv[5]), sys.argv[6], sys.argv[7], sys.argv[8])
FPS = 30000 / 1001
FR = 1000 / FPS
OUT_F, WIN, MIN_RUN, MERGE_GAP, MINF = 9, 0.3, 0.15, 0.7, 25
HOP = 80
hop_t = HOP / 16000

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
    return int(h) * 3600000 + int(m) * 60000 + int(sec) * 1000 + int(ms)


def fmt(t):
    t = int(round(t))
    return f"{t // 3600000:02d}:{t // 60000 % 60:02d}:{t // 1000 % 60:02d},{t % 1000:03d}"


def q(ms):
    return round(round(ms / FR) * FR)


cues = []
for b in open(src, encoding="utf-8-sig").read().replace("\r", "").strip().split("\n\n"):
    l = b.split("\n")
    s, e = (ts(p) for p in l[1].split(" --> "))
    if T0 * 1000 <= s <= T1 * 1000:
        cues.append([s, e, "\n".join(l[2:])])
S = [math.ceil(round(s / 1000 * FPS) / FPS * 1000) for s in json.load(open(shots_p)) if T0 * 1000 - 5000 < s < T1 * 1000 + 5000]


def find_onset(t_ms):
    t = t_ms / 1000 - OFFSET
    lo, hi = max(int((t - WIN) / hop_t), 0), min(int((t + WIN) / hop_t), n - 4)
    if lo >= hi:
        return None, "범위밖"
    base = float(np.percentile(env[max(lo - 60, 0):lo + 1], 20)) if lo > 0 else -80.0
    thr = max(base + 12, -50.0)
    for k in range(lo, hi):
        if env[k] >= thr and env[k:k + 4].mean() >= thr:
            if k == lo:
                return None, "앞말에이어짐"
            return round((k * hop_t + OFFSET) * 1000), "ok"
    return None, "오름없음"


def last_run_end(on_ms, limit_ms):
    i0 = max(int((on_ms / 1000 - OFFSET) / hop_t), 0)
    i1 = min(int((limit_ms / 1000 - OFFSET) / hop_t), n)
    if i1 <= i0 + 4:
        return None
    thr = max(env[i0:i1].max() - 25, -38)
    rs, cur, quiet = [], None, 0
    for k in range(i0 + 3, i1):
        if env[k - 3:k + 1].mean() >= thr:
            if cur is None:
                cur = [k, k]
            cur[1] = k
            quiet = 0
        elif cur is not None:
            quiet += 1
            if quiet * hop_t > 0.12:
                rs.append(cur)
                cur = None
    if cur:
        rs.append(cur)
    merged = []
    for s0, e0 in rs:
        if merged and (s0 - merged[-1][1]) * hop_t <= MERGE_GAP:
            merged[-1][1] = e0
        else:
            merged.append([s0, e0])
    merged = [m for m in merged if (m[1] - m[0]) * hop_t >= MIN_RUN]
    return round(((merged[-1][1] + 1) * hop_t + OFFSET) * 1000) if merged else None


N = len(cues)
adj_in = [j > 0 and cues[j][0] - cues[j - 1][1] <= 150 for j in range(N)]
adj_out = [j + 1 < N and cues[j + 1][0] - cues[j][1] <= 150 for j in range(N)]
res = []
for j, (s, e, tx) in enumerate(cues):
    notes = []
    nin, nout = s, e
    if not adj_in[j]:
        on, st = find_onset(s)
        if on is None:
            notes.append("인점 판독불가:" + st)
        else:
            nin = on
    else:
        notes.append("인점 붙은경계(fix7)")
    if not adj_out[j]:
        nxt = cues[j + 1][0] if j + 1 < N else e + 2000
        en = last_run_end(nin, nxt - 30 if nxt - e < 1500 else e + 1200)
        if en is None:
            notes.append("아웃점 끝판독불가(fix7)")
        else:
            nout = en + OUT_F * FR
    else:
        notes.append("아웃점 붙은경계(fix7)")
    res.append([nin, nout, notes])

# 붙은 경계는 양쪽 큐가 같은 값을 쓰도록 맞춘다
for j in range(1, N):
    if adj_in[j]:
        res[j][0] = res[j - 1][1] if adj_out[j - 1] else res[j][0]

# 인점: 전환 앞뒤 0.5초 안이면 전환 프레임에 붙인다
for r in res:
    c = [s for s in S if 0 < abs(r[0] - s) < 500 and abs(r[0] - s) > FR / 2]
    if c:
        s = min(c, key=lambda v: abs(v - r[0]))
        r[0] = s
        r[2].append("인점 전환에 붙임")
    r[0] = q(r[0])
# 아웃점: 전환 -2프레임이거나 0.5초(15프레임) 이상. 늘리는 후보는 쓰지 않는다
for j, r in enumerate(res):
    o = q(r[1])
    for s in S:
        if abs(o - s) < 500 and abs((s - o) - 2 * FR) > FR / 2 + 10:
            fs = round(s / FR)                                  # 프레임 정수로 계산해 반올림 어긋남을 막는다
            cand = [math.ceil((fs - 2) * FR), math.ceil((fs - 15) * FR), math.ceil((fs + 15) * FR)]
            earlier = [c for c in cand if c <= o + 1]
            o = min(earlier or cand, key=lambda v: abs(v - o))
            r[2].append("아웃점 전환규칙")
    r[1] = o
# 겹침, 최소 길이
for j in range(N - 1):
    if res[j][1] > res[j + 1][0] - 2 * FR + 1 and not adj_out[j]:
        res[j][1] = q(res[j + 1][0] - 2 * FR)
for r in res:
    if r[1] - r[0] < MINF * FR - 1:
        r[1] = q(r[0] + MINF * FR)
        r[2].append("최소길이")

with open(out_srt, "w", encoding="utf-8") as f:
    for j, (r, c) in enumerate(zip(res, cues), 1):
        f.write(f"{j}\n{fmt(r[0])} --> {fmt(r[1])}\n{c[2]}\n\n")
rep = [{"n": j + 1, "fix7_in": c[0], "fix7_out": c[1], "in": r[0], "out": r[1], "notes": r[2]}
       for j, (r, c) in enumerate(zip(res, cues))]
json.dump(rep, open(out_rep, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
unread = sum(1 for r in res if any("판독불가" in t for t in r[2]))
print(f"큐 {N}, 인점·아웃점 판독불가 {unread}, 붙은 경계 인 {sum(adj_in)} 아웃 {sum(adj_out)}, 전환 {len(S)}")
