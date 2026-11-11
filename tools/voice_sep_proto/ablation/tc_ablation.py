"""소리로 TC 잡는 단계를 하나씩 더하며 작업자 교정본과 인점·아웃점을 견준다(2026-11-12, 발표용 예외 — 사용자 허락).

사용: python tc_ablation.py            (세 구간 전부)
      python tc_ablation.py 0406       (한 구간만: 0204 / 0406 / 0608)

- 탐색 기준과 자막 나누기는 fix7 하드섭 초안(.work/hardsub-e01/fix7/final.srt)에서 빌린다. 소리만으로 낸 일치율이 아니다.
- 정답(작업자 교정본)은 평가에만 쓴다. fix7 자막과 정답 자막을 시간 겹침으로 1:1 짝지은 뒤(단계와 무관하게 고정), 단계마다 같은 짝을 잰다.
- 기존 도구 파일은 고치지 않는다. 함수는 원본에서 옮겨 적었고(출처 표시), rules_frames.py는 원본 소스를 읽어 LEAD만 바꿔 실행한다.
- 결과는 각 구간 폴더의 _ablation_20261112/ 에만 쓴다(시각만, 대사 없음).
"""
import csv, json, math, os, sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
from faster_whisper.vad import VadOptions, get_speech_timestamps

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.expanduser(r"~\Documents\subtitle-tc-generator-project")
H = os.path.join(ROOT, "[습작] SDH+번역", "하드섭(자막필요)")
REPO = os.path.join(ROOT, "subtitle-tc-generator")
FIX7 = os.path.join(REPO, ".work", "hardsub-e01", "fix7", "final.srt")
SHOTS = os.path.join(REPO, ".work", "hardsub-e01", "shots_e01.json")
RULES_SRC = os.path.join(REPO, "tools", "voice_sep_proto", "rules_frames.py")
SEGS = {
    "0204": ("E01_음성분리_테스트", 120.0, "final_sdh_sy.srt"),
    "0406": ("E01_음성분리_테스트_04-06분", 240.0, "user_0406_edit.srt"),
    "0608": ("E01_음성분리_테스트_06-08분", 360.0, "E01_06-08분_초안_교정후.srt"),
}
FPS = 30000 / 1001
FR = 1 / FPS
SR, HOP = 16000, 80
hop_t = HOP / SR
TOL1F = 0.034                 # ±1프레임(요청: 34ms)
WIN = 0.3                     # fix7 경계 앞뒤 탐색 폭(onset_snap·voice_tc_draft와 같음)


def ts(s):
    h, m, r = s.strip().split(":")
    sec, ms = r.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def read_srt(p):
    # 블록(빈 줄) 단위로 나누면 빈 줄 없이 붙은 자막을 놓친다(06~08분 정답 58개 중 3개). 시각 줄을 하나씩 읽는다
    out = []
    for l in open(p, encoding="utf-8-sig").read().replace("\r", "").split("\n"):
        if "-->" in l:
            a, e = (ts(x) for x in l.split("-->"))
            out.append((a, e))
    return sorted(out)


def load(wav):
    sr0, x = wavfile.read(wav)
    x = x.astype(np.float32) / 32768
    if x.ndim == 2:
        x = x.mean(1)
    a = resample_poly(x, 160, 441).astype(np.float32) if sr0 == 44100 else x
    n = len(a) // HOP
    sq = (a[: n * HOP] ** 2).reshape(n, HOP).mean(1)
    env = 10 * np.log10(np.convolve(sq, np.ones(2) / 2, "same") + 1e-10)
    return a, env, n


def vad(a):
    # voice_tc.py 33~35행 그대로
    v = get_speech_timestamps(a, VadOptions(threshold=0.5, min_speech_duration_ms=120,
                                            min_silence_duration_ms=200, speech_pad_ms=0))
    return [(x["start"] / SR, x["end"] / SR) for x in v]


# ---- voice_tc.py 47~67행(포락선 경계 다시 잡기) 옮김 ----
def vt_floor(env, n, i0, i1):
    seg = env[max(i0, 0):max(min(i1, n), 1)]
    return float(np.percentile(seg, 20)) if len(seg) else -80.0


def vt_onset(env, n, t, fwd=0.15):
    lo, hi = max(int((t - 0.15) / hop_t), 0), min(int((t + fwd) / hop_t), n - 4)
    thr = max(vt_floor(env, n, lo - 60, lo) + 12.0, -50.0)
    for k in range(lo, hi):
        if env[k] >= thr and env[k:k + 4].mean() >= thr:
            return k * hop_t
    return t


def vt_offset(env, n, t, nxt):
    lo = max(int((t - 0.15) / hop_t), 0)
    hi = min(int((t + 0.3) / hop_t), n - 1, int(nxt / hop_t))
    thr = max(vt_floor(env, n, hi, hi + 60) + 10.0, -50.0)
    last = None
    for k in range(lo, hi):
        if env[k] >= thr:
            last = k
    return (last + 1) * hop_t if last is not None else t


# ---- voice_tc_draft.py 60~72행(소리 오름) 옮김 ----
def draft_onset(env, n, t):
    lo, hi = max(int((t - WIN) / hop_t), 0), min(int((t + WIN) / hop_t), n - 4)
    if lo >= hi:
        return None, "범위밖"
    base = float(np.percentile(env[max(lo - 60, 0):lo + 1], 20)) if lo > 0 else -80.0
    thr = max(base + 12, -50.0)
    for k in range(lo, hi):
        if env[k] >= thr and env[k:k + 4].mean() >= thr:
            if k == lo:
                return None, "앞말에이어짐"
            return k * hop_t, "ok"
    return None, "오름없음"


# ---- onset_snap.py 58~74·81행(판독 ok만, 0.12초 넘으면 far) 옮김 ----
def snap_onset(env, n, t):
    lo, hi = max(int((t - WIN) / hop_t), 0), min(int((t + WIN) / hop_t), n - 4)
    if lo >= hi:
        return None, "out_of_range"
    pre = env[max(lo - 40, 0):lo + 1]
    quiet = pre.max() < -45.0 if len(pre) else False
    base = float(np.percentile(env[max(lo - 60, 0):lo + 1], 20)) if lo > 0 else -80.0
    thr = max(base + 12.0, -50.0)
    for k in range(lo, hi):
        if env[k] >= thr and env[k:k + 4].mean() >= thr:
            if k == lo and env[lo] >= thr:
                return None, "continuous"
            st = "ok" if quiet or env[max(k - 20, 0):k].max() < thr else "weak"
            if st == "ok" and abs(k * hop_t - t) > 0.12:
                st = "far"
            return k * hop_t, st
    return None, "no_onset"


# ---- retime.py 44~56행(음성 끝). 옛 기준과 새 기준을 인자로 ----
def speech_end(env, n, on, limit, drop, floor_db, brk):
    i0, i1 = max(int(on / hop_t), 0), min(int(limit / hop_t), n)
    if i1 <= i0 + 4:
        return None
    thr = max(env[i0:i1].max() - drop, floor_db)
    last, quiet = None, 0
    for k in range(i0 + 3, i1):
        if env[k - 3:k + 1].mean() >= thr:
            last, quiet = k, 0
        elif last is not None:
            quiet += 1
            if quiet * hop_t > brk:
                break
    return (last + 1) * hop_t if last is not None else None


# 1~5단계는 프레임에 맞추지 않는다: 정답·fix7 시각이 0초 기준 29.97fps 격자에 있지 않아(02~04분 확인: 121.150초 = 3630.87프레임)
# 맞추면 단계 차이와 상관없는 0~1프레임 어긋남이 섞인다. 6·7단계는 rules_frames.py가 원래 프레임에 맞추므로 그대로 둔다.
def snap_in(t):
    return t


def snap_out(t):
    return t


def run_rules(voice_rows, outdir, tag):
    """rules_frames.py 원본을 읽어 LEAD만 0으로 바꿔 실행(인점은 이미 소리 오름). LAG=7은 그대로."""
    src = open(RULES_SRC, encoding="utf-8").read()
    assert "LEAD, LAG = 3, 7" in src
    src = src.replace("LEAD, LAG = 3, 7", "LEAD, LAG = 0, 7")
    vj = os.path.join(outdir, f"{tag}.voice.json")
    json.dump(voice_rows, open(vj, "w", encoding="utf-8"), indent=1)
    out_srt, rep = os.path.join(outdir, f"{tag}.srt"), os.path.join(outdir, f"{tag}_report.txt")
    argv0 = sys.argv
    sys.argv = ["rules_frames.py", vj, SHOTS, out_srt, rep]
    try:
        exec(compile(src, "rules_frames.py(LEAD=0)", "exec"), {"__name__": "__main__"})
    finally:
        sys.argv = argv0
    return read_srt(out_srt)


def pair(fx, truth):
    """fix7 자막과 정답 자막을 겹침이 큰 순서로 1:1 짝짓는다. 단계와 무관하게 한 번만."""
    cand = []
    for i, (a, b) in enumerate(fx):
        for j, (c, d) in enumerate(truth):
            ov = min(b, d) - max(a, c)
            if ov > 0:
                cand.append((ov, i, j))
    used_i, used_j, pr = set(), set(), {}
    for ov, i, j in sorted(cand, reverse=True):
        if i not in used_i and j not in used_j:
            pr[i] = j
            used_i.add(i)
            used_j.add(j)
    return pr


def metrics(stage, truth, pr):
    di = np.array([(stage[i][0] - truth[j][0]) * 1000 for i, j in pr.items()])
    do = np.array([(stage[i][1] - truth[j][1]) * 1000 for i, j in pr.items()])
    t1 = TOL1F * 1000
    return {"pairs": len(pr), "in1f": int((abs(di) <= t1).sum()), "in100": int((abs(di) <= 100).sum()),
            "out1f": int((abs(do) <= t1).sum()), "out100": int((abs(do) <= 100).sum()),
            "in_med": float(np.median(abs(di))), "out_med": float(np.median(abs(do))),
            "out_max": float(abs(do).max()), "_di": di, "_do": do}


def segment(key):
    folder, OFF, truth_name = SEGS[key]
    W = os.path.join(H, folder)
    outdir = os.path.join(W, "_ablation_20261112")
    os.makedirs(outdir, exist_ok=True)
    T0, T1 = OFF, OFF + 120
    truth = read_srt(os.path.join(W, truth_name))
    fx = [c for c in read_srt(FIX7) if T0 <= c[0] < T1]
    N = len(fx)
    pr = pair(fx, truth)
    rel = [(a - OFF, b - OFF) for a, b in fx]
    stages, notes = {"R fix7(화면 글자)": list(fx)}, {}
    # 소리로 정한 값의 수(나머지는 fix7 값으로 남은 것). 6·7단계는 규칙이 옮기기 전 기준
    audio_in, audio_out = {"R fix7(화면 글자)": 0}, {"R fix7(화면 글자)": 0}

    # 1·2) VAD 경계만
    env_cache = {}
    for name, wav in (("1 원음+VAD", "mix.wav"), ("2 분리음성+VAD", "voice.wav")):
        a, env, n = load(os.path.join(W, wav))
        env_cache[wav] = (env, n)
        segs = vad(a)
        res, fb_in, fb_out, pick = [], 0, 0, []
        for s, e in rel:
            st = [k for k, (vs, ve) in enumerate(segs) if abs(vs - s) <= WIN]
            ki = min(st, key=lambda k: abs(segs[k][0] - s)) if st else None
            nin = segs[ki][0] if ki is not None else s
            fb_in += ki is None
            en = [k for k, (vs, ve) in enumerate(segs) if nin < ve <= e + WIN]
            ko = max(en, key=lambda k: segs[k][1]) if en else None
            nout = segs[ko][1] if ko is not None else e
            fb_out += ko is None
            res.append((snap_in(nin + OFF), snap_out(nout + OFF)))
            pick.append((ki, ko))
        stages[name] = res
        notes[name] = f"인점 VAD 못 찾아 fix7 {fb_in}, 아웃점 {fb_out}"
        audio_in[name], audio_out[name] = N - fb_in, N - fb_out
        if wav == "voice.wav":
            vsegs, vpick = segs, pick

    env, n = env_cache["voice.wav"]
    # 3) 2 + 5ms 포락선(voice_tc.py 방식)
    s3, s3_raw_in, fb3 = [], [], 0
    for (s, e), (ki, ko) in zip(rel, vpick):
        nin = vt_onset(env, n, vsegs[ki][0]) if ki is not None else s
        if ko is not None:
            nxt = vsegs[ko + 1][0] if ko + 1 < len(vsegs) else n * hop_t
            nout = vt_offset(env, n, vsegs[ko][1], nxt)
        else:
            nout = e
        fb3 += ki is None
        s3_raw_in.append((nin, ki is not None))
        s3.append((snap_in(nin + OFF), snap_out(nout + OFF)))
    stages["3 +5ms 포락선"] = s3
    notes["3 +5ms 포락선"] = notes["2 분리음성+VAD"]
    aud_out3 = audio_out["2 분리음성+VAD"]
    for k in ("3 +5ms 포락선", "4a +옛 인점(3f 전)"):
        audio_in[k], audio_out[k] = audio_in["2 분리음성+VAD"], aud_out3

    # 4a) 옛 인점: 소리 시작 3프레임 전(VAD 못 찾은 곳은 fix7 그대로)
    stages["4a +옛 인점(3f 전)"] = [(snap_in(nin + OFF - 3 * FR) if ok else c[0], c[1])
                                   for (nin, ok), c in zip(s3_raw_in, s3)]
    # 4b) 새 인점: voice_tc_draft 소리 오름(fix7 인점 ±0.3초). voice_tc_draft 106·112행처럼 앞 자막과 150ms 안으로 붙은 경계는
    #     말 중간 분할이라 찾지 않는다. 그 경계와 판독 안 되는 곳은 3단계 값
    adj = [j > 0 and fx[j][0] - fx[j - 1][1] <= 0.150 for j in range(N)]
    in4b, st4b, aud4b = [], [], 0
    for j, ((s, e), (nin3, ok3)) in enumerate(zip(rel, s3_raw_in)):
        on, st = (None, "붙은경계") if adj[j] else draft_onset(env, n, s)
        in4b.append(on if on is not None else nin3)
        st4b.append(st)
        aud4b += on is not None or ok3
    stages["4b +새 인점(소리 오름)"] = [(snap_in(i + OFF), c[1]) for i, c in zip(in4b, s3)]
    notes["4b +새 인점(소리 오름)"] = f"소리 오름 ok {st4b.count('ok')}, 붙은 경계 {sum(adj)}, 나머지는 3단계 인점"
    audio_in["4b +새 인점(소리 오름)"], audio_out["4b +새 인점(소리 오름)"] = aud4b, aud_out3

    # 5a/5b) 말 끝 다시 잡기 + 아웃점 = 말 끝 + 7프레임
    def ends(ins, drop, fl, brk):
        out, fb = [], 0
        for j, on in enumerate(ins):
            limit = ins[j + 1] - 0.03 if j + 1 < N else on + 7
            limit = min(limit, on + 7, n * hop_t)
            en = speech_end(env, n, on, limit, drop, fl, brk)
            fb += en is None
            out.append(en if en is not None else limit)
        return out, fb
    ve_old, fb_old = ends(in4b, 35, -45, 1e9)
    ve_new, fb_new = ends(in4b, 25, -38, 0.35)
    stages["5a +옛 말 끝(-35dB/-45)"] = [(snap_in(i + OFF), snap_out(v + OFF + 7 * FR)) for i, v in zip(in4b, ve_old)]
    stages["5b +새 말 끝(-25dB/-38, 0.35초)"] = [(snap_in(i + OFF), snap_out(v + OFF + 7 * FR)) for i, v in zip(in4b, ve_new)]
    notes["5a +옛 말 끝(-35dB/-45)"] = f"말 끝 못 찾음 {fb_old}"
    notes["5b +새 말 끝(-25dB/-38, 0.35초)"] = f"말 끝 못 찾음 {fb_new}"
    for k, fb in (("5a +옛 말 끝(-35dB/-45)", fb_old), ("5b +새 말 끝(-25dB/-38, 0.35초)", fb_new), ("6 +장면전환 규칙", fb_new)):
        audio_in[k], audio_out[k] = aud4b, N - fb

    # 6) 5b + rules_frames.py(장면전환·간격 메우기·최소 길이)
    rows6 = [{"voice_in": round(i + OFF, 4), "voice_out": round(v + OFF, 4), "text": "-", "basis": "ablation"}
             for i, v in zip(in4b, ve_new)]
    stages["6 +장면전환 규칙"] = run_rules(rows6, outdir, "stage6_rules")

    # 7) 6 + onset_snap: 판독 ok만 소리 오름, 나머지는 fix7 인점으로 되돌림. 말 끝은 새 인점에서 다시 잡음
    in7, st7 = [], []
    for s, e in rel:
        on, st = snap_onset(env, n, s)
        in7.append(on if st == "ok" else s)
        st7.append(st)
    ve7, fb7 = ends(in7, 25, -38, 0.35)
    audio_in["7 +onset_snap"], audio_out["7 +onset_snap"] = st7.count("ok"), N - fb7
    rows7 = [{"voice_in": round(i + OFF, 4), "voice_out": round(v + OFF, 4), "text": "-", "basis": "ablation"}
             for i, v in zip(in7, ve7)]
    stages["7 +onset_snap"] = run_rules(rows7, outdir, "stage7_rules")
    from collections import Counter
    notes["7 +onset_snap"] = "판독 " + ", ".join(f"{k} {v}" for k, v in Counter(st7).items())

    # 결과
    result = {"key": key, "folder": folder, "truth": truth_name, "n_truth": len(truth), "n_fix7": N,
              "pairs": len(pr), "unpaired_truth": len(truth) - len(pr), "unpaired_fix7": N - len(pr), "stages": []}
    with open(os.path.join(outdir, "per_cue.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fix7_n", "truth_n", "truth_in", "truth_out"] + [f"{s}|{x}" for s in stages for x in ("in", "out")])
        for i, j in sorted(pr.items()):
            w.writerow([i + 1, j + 1, f"{truth[j][0]:.3f}", f"{truth[j][1]:.3f}"] +
                       [f"{stages[s][i][k]:.3f}" for s in stages for k in (0, 1)])
    for s, v in stages.items():
        assert len(v) == N, (s, len(v), N)
        m = metrics(v, truth, pr)
        m.pop("_di"); m.pop("_do")
        result["stages"].append({"stage": s, **m, "audio_in": audio_in[s], "audio_out": audio_out[s], "note": notes.get(s, "")})
    json.dump(result, open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[{key}] 정답 {len(truth)} fix7 {N} 짝 {len(pr)}")
    for r in result["stages"]:
        print(f"  {r['stage']:<32} in±1f {r['in1f']:2d} in±100 {r['in100']:2d} out±1f {r['out1f']:2d} out±100 {r['out100']:2d} "
              f"in_med {r['in_med']:6.0f} out_med {r['out_med']:6.0f} out_max {r['out_max']:6.0f} 소리값 in {r['audio_in']} out {r['audio_out']}  {r['note']}")
    return result


if __name__ == "__main__":
    keys = sys.argv[1:] or list(SEGS)
    allres = [segment(k) for k in keys]
    json.dump(allres, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "summary_all.json"), "w",
                          encoding="utf-8"), ensure_ascii=False, indent=1)
