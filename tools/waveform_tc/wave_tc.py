"""분리한 음성(voice.wav)의 파형만 보고 인점·아웃점을 잡는다(SubtitleEdit 기준 규정).

사용: python wave_tc.py VOICE.wav OUT.srt OFFSET_SEC FPS GAP_FRAMES
  VOICE.wav 는 SE 파형 파일(Waveforms/*.wav, 초당 150점)이나 일반 wav.
  GAP_FRAMES = 자막 사이 최소 간격(발주처마다 다름: 0 또는 2). 작업 시작 때 사용자가 정한다.
  [SHOTS.json] = SDH일 때만: 장면전환 시각(ms) 목록. 앞뒤 0.5초 규칙을 적용한다.
규정(사용자 이미지, 2026-11-12):
  인점 = 보이스 시작 전 0.1초(3프레임)
  아웃점 = 보이스 끝난 후 0.2~0.3초(6~9프레임) -> 0.267초
  겹치면 다음 말소리의 인점 우선(앞 자막 아웃점을 다음 인점 - 간격으로 자름)
  아웃점 규칙보다 Minimum Duration 우선(1.0초, 단 다음 인점을 넘지 않음)
파형 판정(내가 정한 값): 10ms 창 RMS, 문턱 = max(하위 20% + 20dB, 상위 1% - 35dB),
  0.2초 이상 조용하면 말소리를 끊고, 0.12초보다 짧은 소리는 버린다.
"""
import sys, wave, json, os
import numpy as np

src, dst = sys.argv[1], sys.argv[2]
offset = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
FPS = eval(sys.argv[4]) if len(sys.argv) > 4 else 30000 / 1001  # 예: 24, 30000/1001
IN_F = round(0.1 * FPS)  # 0.1초
OUT_F = round(0.267 * FPS)  # 0.2~0.3초 가운데(29.97fps에서 8프레임)
MIN_DUR = float(os.environ.get('WAVE_TC_MIN_DUR', '0.834'))  # 넷플릭스 규정 0.833초(5/6초). 발주처마다 다름
if len(sys.argv) <= 5:
    sys.exit("자막 사이 간격(GAP_FRAMES)을 정해 주세요 — 발주처 요청에 따라 0 또는 2")
GAP_F = int(sys.argv[5])
WIN, GAP, MIN_SND = 0.01, 0.2, 0.12

with wave.open(src) as w:
    sr, ch = w.getframerate(), w.getnchannels()
    raw = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, ch) / 32768
if sr < 1000:
    # SubtitleEdit 파형 파일(Waveforms/*.wav, 초당 150점 꼭짓값): SE 화면에 그려지는 파형 그대로 쓴다
    WIN = 1 / sr
    n = len(raw)
    db = 20 * np.log10(np.abs(raw).max(1) + 1e-6)
else:
    x = raw.mean(1)
    hop = int(sr * WIN)
    n = len(x) // hop
    db = 20 * np.log10(np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-12))
thr = max(np.percentile(db, 20) + 20, np.percentile(db, 99) - 35)  # 영상마다 문턱을 정함
on = db > thr
thr_low = thr - 15

segs, i = [], 0
while i < n:
    if on[i]:
        j = i
        while j < n and on[j]:
            j += 1
        # 시작·끝을 넓히지 않는다(넓히면 인점이 너무 앞, 아웃점이 너무 뒤 — 사용자 2026-11-12 지적).
        segs.append([i * WIN, j * WIN, j * WIN])  # 시작, 끝, 끝
        i = j
    else:
        i += 1
merged = []
for s in segs:
    # 나눌지는 넓히기 전(핵심 끝) 기준 쉼 길이로 정한다
    if merged and s[0] - merged[-1][1] < GAP:
        merged[-1][1:] = [s[1], s[2]]
    else:
        merged.append(list(s))
merged = [[s[0], max(s[1], s[2])] for s in merged]
SPLIT_GAP_DENSE = 0.08  # 대사가 많을 때(fill_script.py 가 글자 수로 나눌 때) 쓰는 쉼 기준
voice = [s for s in merged if s[1] - s[0] >= MIN_SND]

# 조각마다 말소리 확률 평균을 보고, 0.5 미만이면 버린다(토이스토리5: 소음 0.38·0.40, 대사 최저 0.55)(환경변수 WAVE_TC_VAD_SRC = VAD 전 분리 음성 wav).
# 계기(2026-11-12): 기계 팔 «덜컥» 소리가 음성 분리를 통과하고 VAD도 부분적으로(0.87~0.91) 말소리로 봐서
# «Star» 앞에 붙었다. 그 조각의 평균은 약 0.47, 진짜 대사는 대부분 0.9 이상.
import os
dropped_vad = []
if os.environ.get("WAVE_TC_VAD_SRC"):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    from checker.vad import _probabilities, find_model, SAMPLE_RATE, WINDOW
    with wave.open(os.environ["WAVE_TC_VAD_SRC"]) as w2:
        sr2 = w2.getframerate()
        m2 = np.frombuffer(w2.readframes(w2.getnframes()), np.int16).reshape(-1, w2.getnchannels()).mean(1) / 32768
    t16 = np.arange(0, len(m2) / sr2, 1 / SAMPLE_RATE)
    prob = np.asarray(_probabilities(np.interp(t16, np.arange(len(m2)) / sr2, m2).astype(np.float32), find_model()))
    step = WINDOW / SAMPLE_RATE
    keep_win = []
    if os.environ.get("WAVE_TC_KEEP"):
        keep_win = [tuple(x[:2]) for x in json.load(open(os.environ["WAVE_TC_KEEP"], encoding="utf-8"))]
    # **VAD는 «이 덩어리가 말인가»를 가리는 데만 쓴다. 경계 자리는 파형으로만 정한다**(사용자 2026-11-12:
    # VAD로 경계를 옮겼더니 VAD가 늦게 올라가 인점이 음성 시작보다 뒤로 갔다).
    # 한 덩어리 안에 말과 비음성이 붙어 있으면(앞뒤 끝에 VAD 0.5 미만이 0.2초 넘게 이어짐),
    # 바뀌는 지점 ±0.15초 안에서 파형이 가장 낮게 꺼지는 자리로 나누고, 나눈 조각마다 다시 가린다.
    def vad_mean(a, b):
        q = prob[int(a / step):max(int(a / step) + 1, int(b / step))]
        return float(q.mean())

    def dip(t):  # t 근처에서 파형이 가장 낮은 자리(초)
        lo, hi = max(0, int((t - 0.15) / WIN)), min(n - 1, int((t + 0.15) / WIN))
        return (lo + int(np.argmin(db[lo:hi + 1]))) * WIN if hi > lo else t

    def split_edges(a, b):
        i0, i1 = int(a / step), max(int(a / step) + 1, int(b / step))
        hi = np.flatnonzero(prob[i0:i1] >= 0.5)
        if not len(hi):
            return [(a, b, False)]
        s0, s1 = (i0 + hi[0]) * step, (i0 + hi[-1] + 1) * step
        parts = []
        # 실제 대사도 시작 0.2초 안팎은 VAD가 낮다 → 확률 낮은 끝 구간이 0.3초 이상이고 그 평균이 0.3 미만일 때만 나눈다
        # (헉·덜컥 같은 비음성은 0.1 안팎, 말의 첫소리는 0.4 안팎이었다)
        cut0 = dip(s0) if s0 - a >= 0.3 and vad_mean(a, s0) < 0.3 else a
        cut1 = dip(s1) if b - s1 >= 0.3 and vad_mean(s1, b) < 0.3 else b
        if cut0 > a:
            parts.append((a, cut0, False))
        parts.append((cut0, cut1, True))
        if cut1 < b:
            parts.append((cut1, b, False))
        return parts

    keep = []
    for s0, s1 in voice:
        if any(a - 0.3 <= s1 and b + 0.3 >= s0 for a, b in keep_win):
            keep.append([s0, s1]); continue
        for a, b, is_core in split_edges(s0, s1):
            if b - a < MIN_SND:
                continue
            (keep if is_core and vad_mean(a, b) >= 0.5 else dropped_vad).append([a, b])
    voice = keep

# 시작·끝을 «눈에 보이는 크기»로 좁힌다(사용자 2026-11-12: «인점·아웃점 둘 다 여유가 너무 많다»).
# SE 화면은 진폭을 그대로 그려서 −28dB 아래(가장 큰 소리 −25dB 아래)는 거의 평평하게 보인다.
# 문턱(thr)으로 잡으면 말 끝의 작은 꼬리(잔향·숨, −28~−40dB)까지 음성으로 봐 아웃점이 약 0.45초 늦었다.
# 조각 전체가 그 크기보다 작으면(«S-» 같은 작은 소리) 좁히지 않는다.
VIS = np.percentile(db, 99) - 25
def _trim(a, b):
    i0, i1 = int(a / WIN), max(int(a / WIN) + 1, int(b / WIN))
    big = np.flatnonzero(db[i0:i1] > VIS)
    if not len(big):
        return a, b
    return (i0 + big[0]) * WIN, (i0 + big[-1] + 1) * WIN
voice = [list(_trim(a, b)) for a, b in voice]
# 끝 꼬리: 말소리 확률 0.2 미만이고 진폭도 작은(가장 큰 소리 −15dB 아래) 꼬리는 잘라낸다
# (대사 뒤 작은 입맞춤·숨소리가 이어져 아웃점이 늦었다). 끝에서는 VAD가 바로 떨어지므로 끝에만 쓴다.
if os.environ.get("WAVE_TC_VAD_SRC"):
    small = np.percentile(db, 99) - 15
    for v in voice:
        if any(a - 0.3 <= v[1] and b + 0.3 >= v[0] for a, b in keep_win):
            continue
        e = v[1]
        while e - v[0] > 0.2 and prob[min(len(prob) - 1, int((e - step) / step))] < 0.2 and db[int((e - WIN) / WIN)] < small:
            e -= WIN
        if e < v[1]:
            v[1] = list(_trim(v[0], e))[1]

fr = lambda t: round(t * FPS)  # 초 -> 프레임 번호
cues = []
for a, b in voice:
    # 인점 = 음성 시작 전 모눈 한 칸(0.1초 이내), 아웃점 = 음성 끝 후 모눈 2.5~3칸(0.25~0.3초) — 사용자 2026-11-12
    i_f = int(np.ceil((a - 0.1) * FPS - 1e-9))
    o_f = int(np.ceil((b + 0.25) * FPS - 1e-9))
    cues.append({"voice": [round(a, 3), round(b, 3)], "in": max(0, i_f), "out": o_f})
# SDH만: 장면전환 앞뒤 0.5초 안에 인점·아웃점이 오지 않게 한다(사용자 2026-11-12).
# 영상 번역 자막은 SHOTS 를 주지 않는다(장면전환 안 씀).
# 내가 정한 처리: 0.5초 안이면 장면전환 프레임으로 붙인다. 단 장면전환이 음성
# 시작 뒤에 있어 인점을 붙이면 음성을 자르게 될 때는 인점을 장면전환 0.5초 앞으로 당긴다.
SHOT_F = round(0.5 * FPS)
if len(sys.argv) > 6:
    shots = [round(ms / 1000 * FPS) for ms in json.load(open(sys.argv[6]))]
    for c in cues:
        v0 = fr(c["voice"][0])
        for s in shots:
            if abs(c["in"] - s) < SHOT_F and s != c["in"]:
                c["in"] = s if s <= v0 else max(0, s - SHOT_F)
                c["shot_in"] = s
            if abs(c["out"] - s) < SHOT_F and s != c["out"] and s > c["in"]:
                c["out"] = s
                c["shot_out"] = s
for k, c in enumerate(cues):
    c["out"] = max(c["out"], c["in"] + int(np.ceil(MIN_DUR * FPS)))  # Minimum Duration 우선
    if k + 1 < len(cues) and c["out"] > cues[k + 1]["in"] - GAP_F:
        c["out"] = cues[k + 1]["in"] - GAP_F  # 다음 인점 우선(발주처 간격만큼 비움)
        c["cut_by_next"] = True
if len(sys.argv) > 6:
    # 마지막 점검: 최소 길이·겹침 처리로 아웃점이 다시 장면전환 0.5초 안에 들어왔으면 장면전환에 붙인다.
    # 다음 자막 인점이 그 장면전환이면 발주처 간격만큼 앞(s - GAP_F)은 허용한다.
    for k, c in enumerate(cues):
        nxt = cues[k + 1]["in"] if k + 1 < len(cues) else None
        for s in shots:
            ok_at = {s, s - GAP_F} if nxt == s else {s}
            if abs(c["out"] - s) < SHOT_F and c["out"] not in ok_at and s > c["in"]:
                c["out"] = s - GAP_F if nxt is not None and nxt <= s else s
                c["shot_out"] = s


def ts(f):
    t = f / FPS + offset
    h, m = divmod(int(t), 3600); m, s = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{int(round((t - int(t)) * 1000)) % 1000:03d}"


with open(dst, "w", encoding="utf-8") as f:
    for k, c in enumerate(cues, 1):
        f.write(f"{k}\n{ts(c['in'])} --> {ts(c['out'])}\n#{k} 음성 {c['voice'][0]:.2f}-{c['voice'][1]:.2f}s\n\n")
json.dump({"threshold_db": thr, "cues": cues}, open(dst + ".json", "w"), ensure_ascii=False, indent=1)
print(f"말소리 확률이 낮아 버린 조각 {len(dropped_vad)}개: " + ", ".join(f"{a:.2f}s" for a, *_ in dropped_vad))
print(f"문턱 {thr:.1f}dB, 자막 {len(cues)}개, 다음 인점에 잘린 것 {sum('cut_by_next' in c for c in cues)}개, "
      f"장면전환에 맞춘 인점 {sum('shot_in' in c for c in cues)}개·아웃점 {sum('shot_out' in c for c in cues)}개")
