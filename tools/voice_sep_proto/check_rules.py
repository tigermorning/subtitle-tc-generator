"""SRT에 적힌 값으로 작업 기본 원칙의 TC 규칙을 검사한다(233·373·600~604행, 간격 메우기·최소 간격)."""
import json, re, sys
srt, shots = sys.argv[1], json.load(open(sys.argv[2]))
FR = 1001 / 30
p = lambda t: round(sum(float(x) * m for x, m in zip(re.split("[:,]", t)[:3], (3600, 60, 1))) * 1000) + int(t[-3:])
cs = []
for b in open(srt, encoding="utf-8").read().strip().split("\n\n"):
    L = b.split("\n"); a, e = [p(x) for x in L[1].split(" --> ")]; cs.append((int(L[0]), a, e))
lo, hi = cs[0][1] - 1000, cs[-1][2] + 1000
import math
FPS = 30000 / 1001
# 전환 시각을 그 프레임의 시작 시각(ms 올림)으로 — SRT에 적히는 값과 같은 기준
S = [math.ceil(round(s / 1000 * FPS) / FPS * 1000) for s in shots if lo < s < hi]
bad = []
for i, (n, a, e) in enumerate(cs):
    for s in S:
        if 0 < abs(a - s) < 500 and abs(a - s) > FR / 2:
            bad.append(f"#{n} 인점 전환 {a - s:+d}ms (딱 붙이거나 0.5초 이상)")
        d = s - e
        if -500 < d < 500 and abs(d - 2 * FR) > FR / 2 + 10:
            bad.append(f"#{n} 아웃점 전환 {-d:+d}ms (전환 -2프레임이거나 0.5초 이상)")
    if e - a < 833: bad.append(f"#{n} 최소 길이 미달 {e - a}ms")
    if i + 1 < len(cs):
        g = cs[i + 1][1] - e
        if g < 2 * FR - 1: bad.append(f"#{n}-#{n+1} 간격 2프레임 미만 {g}ms")
        elif g < 500 and g > 2 * FR + 10: bad.append(f"#{n}-#{n+1} 0.5초 미만 간격 안 메움 {g}ms")
print(f"자막 {len(cs)}, 구간 안 장면전환 {len(S)}, 위반 {len(bad)}")
for x in bad: print(" ", x)
