"""음성 시작·끝(voice.json)에 작업 기본 원칙의 TC 규칙을 프레임 단위로 건다. 시제품.

사용: python rules_frames.py VOICE.json SHOTS.json OUT.srt REPORT.txt
근거(rules/private/sources/작업자-자료/작업 기본 원칙.txt):
  600~604행  인점 = 보이스 시작 전 2~3프레임, 아웃점 = 보이스 끝 후 6~9프레임,
             음성이 겹치면 다음 말소리 인점 우선, 아웃점 규칙보다 Minimum Duration 우선
  200·333행  자막 사이 간격 메우기(500ms 미만) -> 최소 간격(2프레임)
  233·373행  장면전환 앞뒤 0.5초 이내에 걸치지 않는다(넷플릭스 SDH)
             인점은 전환에 딱 맞추거나 0.5초 이상, 아웃점은 전환 -2프레임에 맞추거나 0.5초 이상
  410행      붙일지 벌릴지는 더 자연스러운 쪽 -> 여기서는 덜 움직이는 쪽. 사람 확인 대상으로 남긴다
밀리초로 계산하면 반올림 때문에 전환 1프레임 전·후로 어긋났다(tc_rules_gdocs.py 결과 #27·#30). 그래서 전부 프레임 정수로 계산한다.
자막 [in, out) 프레임: in 프레임부터 보이고 out 프레임에는 없다. SRT에는 각 프레임 시작 시각(ms 올림)을 쓴다.
"""
import json, math, sys

voice, shots_ms, out_srt, report = json.load(open(sys.argv[1], encoding="utf-8")), json.load(open(sys.argv[2])), sys.argv[3], sys.argv[4]
FPS = 30000 / 1001
LEAD, LAG = 3, 7            # 600~601행 범위 안
MIN_LEN = math.ceil(5 / 6 * FPS)        # 833ms = 25프레임
GAP = 2
FILL = math.ceil(0.5 * FPS)             # 0.5초 = 15프레임(14.985)
CLEAR = FILL
f_of = lambda sec: sec * FPS
lo_s, hi_s = voice[0]["voice_in"] - 5, voice[-1]["voice_out"] + 5
SHOTS = sorted(round(s / 1000 * FPS) for s in shots_ms if lo_s * 1000 < s < hi_s * 1000)
log = []

cues = []
for v in voice:
    cues.append({"text": v["text"], "basis": v["basis"],
                 "vin": math.floor(f_of(v["voice_in"])), "vout": math.ceil(f_of(v["voice_out"]))})
for c in cues:
    c["in"], c["out"] = max(c["vin"] - LEAD, 0), c["vout"] + LAG


def near(t, before, after):
    """t가 전환 S 기준 (S - before, S + after) 안이면 그 S(가장 가까운 것)"""
    best = None
    for s in SHOTS:
        if s - before < t < s + after and (best is None or abs(t - s) < abs(t - best)):
            best = s
    return best


def shot_between(a, b):
    return [s for s in SHOTS if a < s <= b]


def ok_in(x):
    """인점: 전환에 딱 붙었거나 모든 전환에서 0.5초 이상"""
    return all(x == s or abs(x - s) >= CLEAR for s in SHOTS)


def ok_out(x):
    """아웃점: 전환 -2프레임이거나 모든 전환에서 0.5초 이상"""
    return all(x == s - GAP or abs(x - s) >= CLEAR for s in SHOTS)


def pass_once():
    # 단계마다 자막 전체를 돈다(인점 -> 간격 -> 아웃점 -> 최소 길이). 자막 하나씩 네 단계를 다 하면
    # 다음 자막 인점이 전환에 붙기 전에 앞 자막 아웃점을 정해, 전환 -2프레임 자리가 없다고 보고 0.5초 당겼다(#10~#12)
    changed = False
    for i, c in enumerate(cues):
        prev = cues[i - 1] if i else None
        nxt = cues[i + 1] if i + 1 < len(cues) else None
        max_out = nxt["in"] - GAP if nxt else 10 ** 9
        # 1) 장면전환: 인점. 전환이 둘 이상 가까이 있을 수 있어(13프레임 간격 5331·5344) 모든 전환을 한꺼번에 만족하는 값만 후보로 둔다.
        #    최소 길이가 설 자리(max_out - x >= MIN_LEN)도 있어야 한다(604행: Minimum Duration 우선)
        if not ok_in(c["in"]):
            s = near(c["in"], CLEAR, CLEAR)
            lo = prev["in"] + 1 if prev else 0
            pool = {x for t in SHOTS if abs(t - c["in"]) < 2 * CLEAR for x in (t, t - CLEAR, t + CLEAR)}
            cands = [x for x in pool if ok_in(x) and lo <= x and max_out - x >= MIN_LEN]
            if cands:
                new = min(cands, key=lambda x: (abs(x - c["in"]), x not in SHOTS))
                log.append((i + 1, "in", c["in"], new, f"전환 {s}f에서 {c['in'] - s:+d}f — {'전환에 붙임' if new in SHOTS else '0.5초 벌림'}"))
                c["in"], changed = new, True
            else:
                log.append((i + 1, "in", c["in"], None, f"전환 {s}f에서 {c['in'] - s:+d}f — 옮길 자리 없음(확인 필요)"))
    for i, c in enumerate(cues):
        prev = cues[i - 1] if i else None
        nxt = cues[i + 1] if i + 1 < len(cues) else None
        max_out = nxt["in"] - GAP if nxt else 10 ** 9
        # 2) 겹침은 다음 인점 우선, 0.5초 미만 간격은 메움 -> 2프레임
        if nxt:
            gap = nxt["in"] - c["out"]
            if gap < GAP or (GAP < gap < FILL):
                new = nxt["in"] - GAP
                cross = shot_between(c["out"], new) if new > c["out"] else []
                if cross:          # 메우다가 전환을 넘으면 전환 -2프레임에서 멈춘다
                    new = max(cross[0] - GAP, c["out"])
                if new != c["out"]:
                    log.append((i + 1, "out", c["out"], new, f"다음 자막과 간격 {gap}f — {'겹침 해소' if gap < 0 else '간격 정리'}"))
                    c["out"], changed = new, True
    for i, c in enumerate(cues):
        prev = cues[i - 1] if i else None
        nxt = cues[i + 1] if i + 1 < len(cues) else None
        max_out = nxt["in"] - GAP if nxt else 10 ** 9
        # 3) 장면전환: 아웃점
        if not ok_out(c["out"]):
            s = near(c["out"], CLEAR, CLEAR)
            pool = {x for t in SHOTS if abs(t - c["out"]) < 2 * CLEAR for x in (t - GAP, t - CLEAR, t + CLEAR)}
            cands = [x for x in pool if ok_out(x) and c["in"] + MIN_LEN <= x <= max_out]
            if cands:
                new = min(cands, key=lambda x: (abs(x - c["out"]), x + GAP not in SHOTS))
                log.append((i + 1, "out", c["out"], new, f"전환 {s}f에서 {c['out'] - s:+d}f — {'전환 2프레임 전' if new + GAP in SHOTS else '0.5초 벌림'}"))
                c["out"], changed = new, True
            else:
                log.append((i + 1, "out", c["out"], None, f"전환 {s}f에서 {c['out'] - s:+d}f — 옮길 자리 없음(확인 필요)"))
    for i, c in enumerate(cues):
        prev = cues[i - 1] if i else None
        nxt = cues[i + 1] if i + 1 < len(cues) else None
        max_out = nxt["in"] - GAP if nxt else 10 ** 9
        # 4) 최소 길이 우선(604행)
        if c["out"] - c["in"] < MIN_LEN:
            hi = nxt["in"] - GAP if nxt else 10 ** 9
            new = min(c["in"] + MIN_LEN, hi)
            if new != c["out"]:
                log.append((i + 1, "out", c["out"], new, f"최소 길이 {MIN_LEN}f"))
                c["out"], changed = new, True
    return changed


for rnd in range(6):
    if not pass_once():
        break
print(f"규칙 반복 {rnd + 1}회")


def ms(frame):
    return math.ceil(frame / FPS * 1000)


def fmt(m):
    return f"{m//3600000:02d}:{m//60000%60:02d}:{m//1000%60:02d},{m%1000:03d}"


# 검증(프레임 기준)
bad = []
for i, c in enumerate(cues):
    for s in SHOTS:
        if 0 < abs(c["in"] - s) < CLEAR:
            bad.append(f"#{i+1} 인점 전환 {c['in'] - s:+d}f")
        if 0 < abs(c["out"] - (s - GAP)) and -CLEAR < c["out"] - s < CLEAR:
            bad.append(f"#{i+1} 아웃점 전환 {c['out'] - s:+d}f")
    if c["out"] - c["in"] < MIN_LEN:
        bad.append(f"#{i+1} 최소 길이 {c['out'] - c['in']}f")
    if i + 1 < len(cues):
        g = cues[i + 1]["in"] - c["out"]
        if g < GAP:
            bad.append(f"#{i+1} 간격 {g}f")
        elif GAP < g < FILL and not shot_between(c["out"], cues[i + 1]["in"]):
            bad.append(f"#{i+1} 0.5초 미만 간격 {g}f 안 메움")
lead = [c["vin"] - c["in"] for c in cues]
lag = [c["out"] - c["vout"] for c in cues]
print(f"자막 {len(cues)}, 전환 {len(SHOTS)}, 규칙 위반 {len(bad)}")
for b in bad:
    print(" ", b)
off_lead = [(i + 1, l) for i, l in enumerate(lead) if not 2 <= l <= 3]
print(f"인점이 음성 시작 2~3프레임 전이 아닌 자막 {len(off_lead)}: {off_lead}")
print(f"아웃점이 음성 끝 6~9프레임 뒤가 아닌 자막 {sum(1 for l in lag if not 6 <= l <= 9)}")

with open(out_srt, "w", encoding="utf-8") as f:
    for i, c in enumerate(cues, 1):
        f.write(f"{i}\n{fmt(ms(c['in']))} --> {fmt(ms(c['out']))}\n{c['text']}\n\n")
with open(report, "w", encoding="utf-8") as f:
    f.write("# 조정 기록(프레임, 29.97fps). f = 프레임 번호\n")
    for n, w, a, b, m in log:
        f.write(f"#{n} {w} {a}f({fmt(ms(a))}) -> {'-' if b is None else f'{b}f({fmt(ms(b))})'}  {m}\n")
    f.write(f"\n# 규칙 위반으로 남은 것 {len(bad)}\n" + "".join(b + "\n" for b in bad))
    f.write("\n# 인점-음성 시작(프레임, 양수 = 음성보다 먼저 뜸) / 아웃점-음성 끝(양수 = 음성 뒤까지 남음)\n")
    for i, c in enumerate(cues, 1):
        f.write(f"#{i} lead {c['vin'] - c['in']:+d}f  lag {c['out'] - c['vout']:+d}f  [{c['basis']}] {c['text'].splitlines()[0]}\n")
print("wrote", out_srt, report)
