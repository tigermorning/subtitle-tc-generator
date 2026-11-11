"""tc_ablation.py가 쓴 summary_all.json -> 단계별 표(md 조각). 숫자만, 대사 없음.

사용: python make_table.py [--out 폴더]
읽는 위치: --out > 환경 변수 TC_ABLATION_OUT > <TC_ABLATION_DATA 또는 기본 자료 폴더>/_ablation_20261112
(tc_ablation.py가 쓰는 자리와 같다. 자료와 결과는 DESKTOP-T8TGMOP에만 있다)
"""
import argparse, json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
DEFAULT_DATA = os.path.join(os.path.expanduser(r"~\Documents\subtitle-tc-generator-project"), "[습작] SDH+번역", "하드섭(자막필요)")
ap = argparse.ArgumentParser()
ap.add_argument("--out", help="summary_all.json이 든 폴더")
a = ap.parse_args()
D = a.out or os.environ.get("TC_ABLATION_OUT") or os.path.join(os.environ.get("TC_ABLATION_DATA") or DEFAULT_DATA, "_ablation_20261112")
p = os.path.join(D, "summary_all.json")
if not os.path.isfile(p):
    print(f"{p} 가 없다. 먼저 tc_ablation.py를 돌린다(자료는 DESKTOP-T8TGMOP에만 있음).", file=sys.stderr)
    sys.exit(2)
res = json.load(open(p, encoding="utf-8"))
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
