"""작업자 자료(구글 독스) TC 규정 적용: 자막 간격 + 장면전환. 시제품.

근거(rules/private/sources/작업자-자료/작업 기본 원칙.txt):
  - 자막 사이 간격 메우기(500ms 미만 간격을 이전 자막 아웃점 연장으로 메움) -> 그 다음 최소간격(2프레임) 설정.
  - 자막이 장면 전환 앞뒤 0.5초 이내에 걸치지 않게: 딱 붙이거나 0.5초 이상 벌린다. 더 자연스러운 쪽.
      인점: 장면전환에 딱 맞추기(전환 첫 프레임) 또는 0.5초 이상 벌리기
      아웃점: 장면전환 -2프레임 또는 0.5초 이상 벌리기
  - 쿠팡은 비적용, 넷플릭스·디즈니는 적용. SDH만.
사용: python tc_rules.py IN.srt SHOTS.json OUT.srt REPORT.txt [FPS]
"""
import json, re, sys

in_srt, shots_json, out_srt, report = sys.argv[1:5]
FPS = float(sys.argv[5]) if len(sys.argv) > 5 else 30000 / 1001
FR = 1000.0 / FPS
GAP = 70                     # 최소 간격 2프레임(66.7ms) 이상, 10ms 단위 내림 뒤에도 유지되도록 70ms
FILL = 500                   # 간격 메우기 기준
CLEAR = 500                  # 장면전환 앞뒤 여유
AWAY = CLEAR + 10            # 벌릴 때 목표: 10ms 내림 뒤에도 0.5초 이상이 되도록 10ms 더
OUT_LEAD = round(2 * FR)     # 아웃점은 전환 2프레임 전
KEEP = 300                   # 인점·아웃점 조정 후에도 남겨 둘 최소 길이(이보다 짧아지면 조정을 포기하고 표시)
SHOTS = json.load(open(shots_json))
log = []


def parse(ts):
    h, m, s, ms = map(int, re.findall(r"\d+", ts))
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def fmt(ms):
    ms = int(ms // 10 * 10)      # SE 미리보기(ASS 10ms 반올림)에서도 그 프레임에 뜨도록 10ms 내림
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"


cues, notes = [], []
for b in open(in_srt, encoding="utf-8").read().strip().split("\n\n"):
    L = b.split("\n")
    a, e = [parse(x) for x in L[1].split(" --> ")]
    c = {"n": int(L[0]), "in": a, "out": e, "text": "\n".join(L[2:]), "in0": a, "out0": e}
    (notes if c["text"].startswith("[읽기 실패]") else cues).append(c)
print(f"cues {len(cues)}, 읽기 실패(제외) {len(notes)}, 장면전환 {len(SHOTS)}, 간격 {GAP}ms, fps {FPS:.3f}")


def near_shot(t, lo, hi):
    """t 기준 (lo, hi) 안에 있는 가장 가까운 장면전환 하나."""
    best = None
    for s in SHOTS:
        if lo < t - s < hi and (best is None or abs(t - s) < abs(t - best)):
            best = s
    return best


def fix_in(c, prev):
    t = c["in"]
    s = near_shot(t, -CLEAR, CLEAR)
    if s is None or abs(t - s) <= FR:          # 전환 없음 / 이미 딱 붙음
        return
    lo = (prev["in"] + KEEP) if prev else 0
    hi = c["out"] - KEEP
    cands = [s, s + AWAY if t > s else s - AWAY]
    cands = [x for x in cands if lo <= x <= hi]
    if not cands:
        log.append((c["n"], "in", t, None, f"장면전환 {s}ms 근처지만 조정할 자리가 없어 그대로 둠(확인 필요)"))
        return
    new = min(cands, key=lambda x: (abs(x - t), x != s))   # 이동이 작은 쪽, 같으면 딱 붙이기
    kind = "전환에 딱 붙임" if new == s else "전환에서 0.5초 벌림"
    log.append((c["n"], "in", t, new, f"장면전환 {s}ms에서 {t - s:+d}ms — {kind}"))
    c["in"] = int(round(new))


def fix_out(c, nxt):
    t = c["out"]
    s = near_shot(t, -CLEAR, CLEAR)
    if s is None:
        return
    target = s - OUT_LEAD
    if abs(t - target) <= FR:
        return
    lo = c["in"] + KEEP
    hi = (nxt["in"] - GAP) if nxt else 10 ** 12
    cands = [target, s + AWAY if t > s else s - AWAY]
    cands = [x for x in cands if lo <= x <= hi]
    if not cands:
        log.append((c["n"], "out", t, None, f"장면전환 {s}ms 근처지만 조정할 자리가 없어 그대로 둠(확인 필요)"))
        return
    new = min(cands, key=lambda x: (abs(x - t), x != target))
    kind = "전환 2프레임 전" if new == target else "전환에서 0.5초 벌림"
    log.append((c["n"], "out", t, new, f"장면전환 {s}ms에서 {t - s:+d}ms — {kind}"))
    c["out"] = int(round(new))


def fill_gaps():
    """간격 메우기(500ms 미만) -> 최소간격 2프레임. 겹침(음수 간격)도 여기서 걷힌다."""
    for i in range(1, len(cues)):
        p, c = cues[i - 1], cues[i]
        if c["in"] - p["out"] < FILL:
            new = c["in"] - GAP
            if new != p["out"]:
                why = "겹침 해소" if c["in"] < p["out"] else "간격 정리"
                if new - p["in"] < KEEP:
                    log.append((p["n"], "out", p["out"], new, f"{why}하면 {new - p['in']}ms로 너무 짧아짐 — 표시"))
                log.append((p["n"], "out", p["out"], new, f"다음 자막(#{c['n']}) 인점과 {c['in'] - p['out']:+d}ms — {why}(2프레임)"))
                p["out"] = new


for rnd in range(3):     # 장면전환 조정 <-> 간격 정리가 서로 밀지 않을 때까지
    before = [(c["in"], c["out"]) for c in cues]
    for i, c in enumerate(cues):
        fix_in(c, cues[i - 1] if i else None)
    fill_gaps()
    for i, c in enumerate(cues):
        fix_out(c, cues[i + 1] if i + 1 < len(cues) else None)
    fill_gaps()
    if before == [(c["in"], c["out"]) for c in cues]:
        break

# ---- 검증 ----
bad_overlap = sum(1 for i in range(1, len(cues)) if cues[i]["in"] < cues[i - 1]["out"])
bad_gap = sum(1 for i in range(1, len(cues)) if 0 <= cues[i]["in"] - cues[i - 1]["out"] < GAP - 1)
mid_gap = sum(1 for i in range(1, len(cues)) if GAP + 1 < cues[i]["in"] - cues[i - 1]["out"] < FILL)
inv = sum(1 for c in cues if c["out"] <= c["in"])
short = sum(1 for c in cues if c["out"] - c["in"] < 833)


def shot_violation(c):
    v = []
    a, b = c["in"] // 10 * 10, c["out"] // 10 * 10      # 실제로 적히는 값
    s = near_shot(a, -CLEAR, CLEAR)
    if s is not None and abs(a - s) > FR + 10:
        v.append(f"in {a - s:+d}ms")
    s = near_shot(b, -CLEAR, CLEAR)
    if s is not None and abs(b - (s - OUT_LEAD)) > FR + 10:
        v.append(f"out {b - s:+d}ms")
    return v


left = [(c["n"], shot_violation(c)) for c in cues if shot_violation(c)]
print(f"겹침 {bad_overlap}, 간격 2프레임 미만 {bad_gap}, 간격 2프레임~0.5초 미정리 {mid_gap}, 길이 역전 {inv}")
print(f"장면전환 0.5초 안에 남은 자막 {len(left)}, 최소 길이(833ms) 미달 {short}")
moved_in = sum(1 for c in cues if c["in"] != c["in0"])
moved_out = sum(1 for c in cues if c["out"] != c["out0"])
print(f"인점 바뀐 자막 {moved_in}, 아웃점 바뀐 자막 {moved_out}")

with open(out_srt, "w", encoding="utf-8") as f:
    for k, c in enumerate(cues, 1):
        f.write(f"{k}\n{fmt(c['in'])} --> {fmt(c['out'])}\n{c['text']}\n\n")
with open(report, "w", encoding="utf-8") as f:
    f.write(f"# 조정 기록 (원 번호 기준) — 간격 {GAP}ms, 장면전환 여유 {CLEAR}ms\n")
    for n, w, a, b, msg in log:
        f.write(f"#{n} {w} {fmt(a)} -> {fmt(b) if b is not None else '-'}  {msg}\n")
    f.write(f"\n# 장면전환 0.5초 안에 남은 자막 {len(left)}건\n")
    for n, v in left:
        f.write(f"#{n} {', '.join(v)}\n")
    f.write(f"\n# 제외한 [읽기 실패] 구간 {len(notes)}건\n")
    for c in notes:
        f.write(f"#{c['n']} {fmt(c['in0'])} --> {fmt(c['out0'])}\n")
print("wrote", out_srt, report)
