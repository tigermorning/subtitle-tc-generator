"""summary_all.json -> 단계별 표(md 조각). 숫자만, 대사 없음."""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
D = os.path.dirname(os.path.abspath(__file__))
res = json.load(open(os.path.join(D, "summary_all.json"), encoding="utf-8"))
NAMES = {"0204": "02~04분", "0406": "04~06분", "0608": "06~08분"}
out = []
for r in res:
    out.append(f"### {NAMES[r['key']]} — 정답 `{r['truth']}` {r['n_truth']}개, fix7 {r['n_fix7']}개, 짝 {r['pairs']}쌍 "
               f"(짝 없음: 정답 {r['unpaired_truth']}, fix7 {r['unpaired_fix7']})\n")
    out.append("| 단계 | 인점 ±1f | 인점 ±100ms | 아웃 ±1f | 아웃 ±100ms | 인점 오차 중앙(ms) | 아웃 오차 중앙(ms) | 아웃 최대 오차(ms) | 소리로 정한 인점/아웃 |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for s in r["stages"]:
        out.append(f"| {s['stage']} | {s['in1f']} | {s['in100']} | {s['out1f']} | {s['out100']} | {s['in_med']:.0f} | "
                   f"{s['out_med']:.0f} | {s['out_max']:.0f} | {s['audio_in']}/{s['audio_out']} |")
    out.append("")
# 세 구간 합계(짝 수 합, 개수 합). 중앙값은 구간별로만 낸다
out.append("### 세 구간 합계 (개수만 더함)\n")
tot = sum(r["pairs"] for r in res)
out.append(f"| 단계 | 인점 ±1f (/{tot}) | 인점 ±100ms | 아웃 ±1f | 아웃 ±100ms |")
out.append("|---|---|---|---|---|")
for k, s0 in enumerate(res[0]["stages"]):
    v = [sum(r["stages"][k][m] for r in res) for m in ("in1f", "in100", "out1f", "out100")]
    out.append(f"| {s0['stage']} | {v[0]} | {v[1]} | {v[2]} | {v[3]} |")
print("\n".join(out))
