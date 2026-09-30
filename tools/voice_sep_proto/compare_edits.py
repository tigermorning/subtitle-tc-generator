"""사용자 수정본과 초안·화면 글자 판의 TC 일치율을 잰다. 대사가 없는 CSV만 읽는다.

사용: python compare_edits.py docs/evidence/voice_sep_user_edits_e01.csv
열: segment, n, fix7_in, fix7_out, draft_in, draft_out, user_in, user_out (초 단위)
새 구간을 검증하면 같은 열로 행을 덧붙인다(초안은 사용자가 고치기 전에 만든 것이어야 한다).
"""
import csv, sys
from collections import defaultdict

rows = defaultdict(list)
for r in csv.DictReader(open(sys.argv[1], encoding="utf-8")):
    rows[r["segment"]].append({k: float(v) for k, v in r.items() if k not in ("segment",)})

def hit(rs, a, b, tol_ms):
    return sum(abs(r[a] - r[b]) * 1000 <= tol_ms for r in rs)

for seg, rs in rows.items():
    n = len(rs)
    print(f"[{seg}] 자막 {n}")
    for name, pi, po in (("화면 글자(fix7)", "fix7_in", "fix7_out"), ("초안(학습 기준 적용)", "draft_in", "draft_out")):
        print(f"  {name:<18} 인점 ±34ms {hit(rs, pi, 'user_in', 34):>2}  ±100ms {hit(rs, pi, 'user_in', 100):>2}"
              f"   아웃점 ±34ms {hit(rs, po, 'user_out', 34):>2}  ±100ms {hit(rs, po, 'user_out', 100):>2}")
    ci = sum(abs(r["draft_in"] - r["user_in"]) > 5e-4 for r in rs)
    co = sum(abs(r["draft_out"] - r["user_out"]) > 5e-4 for r in rs)
    print(f"  사용자가 초안에서 바꾼 것: 인점 {ci}, 아웃점 {co}")
