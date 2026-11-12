"""넘기기 전 TC 전수 점검: 자막마다 인점·아웃점이 실제 말소리 시작·끝과 규정대로 맞는지 본다.

사용: python check_tc.py CLIP.srt SE_WAVEFORM.wav VOICE_SEP.wav FPS GAP_FRAMES [SDH_REF.srt OFFSET]
음성 경계 = SE 파형에서 보이는 크기(상위 1% − 25dB)를 넘는 첫·마지막 자리(VAD로 재지 않는다).
점검:
 - 인점: 말소리 시작 전 0~0.1초(+1프레임 반올림 여유)
 - 아웃점: 말소리 끝 후 0.25~0.3초(+1프레임). 다음 인점에 막혔거나 최소 1초를 채운 경우는 예외
 - 말소리에서 SDH 소리 표기 시간은 뺀다. 2차 패스로 되살린 자막(VAD가 놓친 외침 등)은 «귀로 확인»으로 따로 보고
 - SDH 소리 표기(선택): 자막 안 말소리가 대괄호 표기 줄 시간과 절반 넘게 겹치면 안 됨
"""
import re, sys, wave, os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from checker.vad import _probabilities, find_model, SAMPLE_RATE, WINDOW

srt, sew, vsep, fps, gap = sys.argv[1], sys.argv[2], sys.argv[3], eval(sys.argv[4]), int(sys.argv[5])
F = 1 / fps


def rd(p, off=0.0):
    t = open(p, encoding="utf-8-sig").read()
    f = lambda h, m, s, ms: int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    return [(int(b[0]), f(*b[1:5]) - off, f(*b[5:9]) - off, b[9].replace("\n", " "))
            for b in re.findall(r"(\d+)\n(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)\n(.*?)(?:\n\n|\Z)", t, re.S)]


with wave.open(sew) as w:
    y = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels()) / 32768
db = 20 * np.log10(np.abs(y).max(1) + 1e-6); dt = 1 / 150
VIS = np.percentile(db, 99) - 25
with wave.open(vsep) as w:
    sr = w.getframerate(); x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels()).mean(1) / 32768
t16 = np.arange(0, len(x) / sr, 1 / SAMPLE_RATE)
prob = np.asarray(_probabilities(np.interp(t16, np.arange(len(x)) / sr, x).astype(np.float32), find_model()))
st = WINDOW / SAMPLE_RATE
pr = lambda t: prob[min(len(prob) - 1, int(t / st))]
sounds = []
if len(sys.argv) > 7:
    sounds = [(a, b) for _, a, b, txt in rd(sys.argv[6], float(sys.argv[7]))
              if txt.strip() and not re.sub(r"\[[^\]]*\]|[♪\s-]|<[^>]+>", "", txt)]

cues = rd(srt)
MIN_DUR = float(os.environ.get('WAVE_TC_MIN_DUR', '0.834'))
TOL = 0.01  # VAD 판정 단위(32ms)와 파형 단위(6.7ms) 차이로 생기는 측정 오차
keep_win = []
kp = os.path.join(os.path.dirname(os.path.abspath(srt)), "keep_script.json")
if os.path.exists(kp):
    import json
    keep_win = [tuple(x[:2]) for x in json.load(open(kp, encoding="utf-8"))]
check_by_ear = []
bad = 0
for k, (n, a, b, txt) in enumerate(cues):
    ts = np.arange(a, b, dt)
    in_sound = lambda t: any(y0 <= t < y1 for y0, y1 in sounds)
    lv = lambda t: db[max(0, min(len(db) - 1, int(t / dt)))]
    # 경계는 파형으로 잰다(보이는 크기). VAD로 재면 VAD가 늦게 올라가는 만큼 틀린 인점을 «맞다»고 통과시켰다
    speech_t = [t for t in ts if lv(t) > VIS]
    # 쉼(0.08초 이상)으로 떨어진 덩어리로 나눈다. 아웃점 앞 0.2초 안에서 새로 시작한 덩어리는 다른 소리로 본다
    runs = []
    for t in speech_t:
        if runs and t - runs[-1][1] <= 0.08:
            runs[-1][1] = t + dt
        else:
            runs.append([t, t + dt])
    runs = [r for r in runs if r[0] < b - 0.2] or runs
    speech = [runs[0][0], runs[-1][1] - dt] if runs else []
    prev_b = cues[k - 1][2] if k > 0 else -1
    nxt_a = cues[k + 1][1] if k + 1 < len(cues) else 1e9
    chained_in = abs(a - prev_b) < F / 2 + 0.001 + gap * F   # 앞 자막과 맞닿음(쉼 없는 말을 나눈 자리)
    chained_out = abs(nxt_a - b) < F / 2 + 0.001 + gap * F
    rescued = any(a - 0.5 <= y1 and b + 0.5 >= y0 for y0, y1 in keep_win)
    probs = []
    if rescued:
        check_by_ear.append(f"#{n} {a:7.3f}-{b:7.3f} {txt[:30]}")
        continue
    if not speech:
        probs.append("말소리가 없음")
    else:
        s0, s1 = speech[0], speech[-1] + dt
        lead, tail = s0 - a, b - s1
        nxt = cues[k + 1][1] if k + 1 < len(cues) else 1e9
        # 인점 바로 앞(0.05초 안)에 이미 소리가 있으면 첫소리가 잘린 것
        if not chained_in and s0 - a < dt * 1.5 and any(lv(a - k * dt) > VIS for k in range(1, 8)):
            probs.append("인점이 음성 시작보다 뒤(첫소리 잘림)")
        if not chained_in and not (-TOL <= lead <= 0.1 + F + TOL):
            probs.append(f"인점이 말소리 시작보다 {lead:.3f}초 앞(규정 0~0.1)")
        cut = chained_out or abs(b - (nxt - gap * F)) < F / 2 + 0.001 or abs((b - a) - MIN_DUR) < F + 0.001
        if not cut and not chained_out and any(lv(b + k * dt) > VIS for k in range(0, 4)) and b - s1 < dt * 1.5:
            # 뒤에 붙은 소리가 말소리 확률이 낮으면(외침·웃음 등) 파형만으로는 말의 끝을 못 가린다 → 귀로 확인
            if np.mean([pr(b + k * 0.05) for k in range(6)]) < 0.5:
                check_by_ear.append(f"#{n} {a:7.3f}-{b:7.3f} {txt[:30]} (말 뒤에 비음성이 쉼 없이 붙음 — 말 끝 확인)")
                continue
            probs.append("아웃점 뒤에도 소리가 이어짐(끝소리 잘림)")
        if not cut and not (0.25 - TOL <= tail <= 0.3 + F + TOL):
            probs.append(f"아웃점이 말소리 끝보다 {tail:.3f}초 뒤(규정 0.25~0.3)")
        ins = sum(max(0, min(s1, y1) - max(s0, y0)) for y0, y1 in sounds)
        if s1 > s0 and ins / (s1 - s0) > 0.5:
            probs.append("SDH 소리 표기 시간과 절반 넘게 겹침")
    if probs:
        bad += 1
        print(f"#{n} {a:7.3f}-{b:7.3f} {txt[:30]} → " + "; ".join(probs))
print(f"점검: 자막 {len(cues)}개, 문제 {bad}개, 귀로 확인 필요 {len(check_by_ear)}개")
for x in check_by_ear:
    print("  귀로 확인:", x)
