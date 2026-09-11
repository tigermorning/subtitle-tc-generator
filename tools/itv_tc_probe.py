"""IWSLT ITV dev 7편(.tmp/iwslt/itv/dev) — 영어 전문 자막을 VAD 대비로 재서 TC 관행을 뽑는다.

A층(생성 없음). `tc_residual_probe.py`의 A 부분과 같은 측정을 다른 발주처(영국 ITV)에 댄 것.
결과와 판단은 `rules/learned/itv/en-sdh.yaml`(2026-09-11). 시리즈마다 스포팅 품질이 달라
합산값보다 시리즈별로 봐야 한다 — rows.json을 남기므로 시리즈별 재집계는 거기서 한다.
자료 자체는 비상업·재배포 금지(README) — 저장소에 없다. 다시 받는 곳: iwslt.org/2025/subtitling.

용법: python tools/itv_tc_probe.py [01 02 ...]   (VAD·전환 캐시는 .tmp/iwslt/probe/)
"""
import os, re, sys, bisect, json, statistics as st
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path("C:/Users/user/Documents/subtitle-tc-generator"); os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from checker.parsers import parse
from checker.vad import detect_speech
from checker.media import detect_shot_changes
BASE = ROOT / ".tmp/iwslt/itv/dev"; OUT = ROOT / ".tmp/iwslt/probe"; OUT.mkdir(exist_ok=True)
SFX = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪?)\s*$")
FPS = {"01": 23.976, "02": 23.976, "03": 23.976, "04": 25, "05": 25, "06": 25, "07": 25}

def is_sfx(e):
    ls = [l for l in e.text.split("\n") if l.strip()]
    return bool(ls) and all(SFX.match(re.sub(r"<[^>]+>", "", l)) for l in ls)
def nearest(vals, x):
    i = bisect.bisect_left(vals, x); c = [vals[j] for j in (i-1, i) if 0 <= j < len(vals)]
    return min(c, key=lambda v: abs(v-x)) if c else None
def q(v, label):
    v = sorted(v); n = len(v)
    if not n: return f"{label}: n=0"
    ab = sorted(abs(x) for x in v)
    return (f"{label:30s} n={n:4d} 가운데 {st.median(v):+5.0f} |중앙| {st.median(ab):4.0f} 100ms안 {sum(x<=100 for x in ab)/n:4.0%} "
            f"사분위 {v[n//4]:+5.0f}/{v[3*n//4]:+5.0f}")

allrows = []
for ep in sys.argv[1:] or sorted(FPS):
    video = BASE / "video" / f"{ep}.mp4"; truth = parse(BASE / "srt/en" / f"{ep}.srt")
    fps = FPS[ep]; frame = 1000 / fps
    vc = OUT / f"vad_{ep}.json"; sc = OUT / f"shots_{ep}.json"
    speech = json.loads(vc.read_text()) if vc.exists() else detect_speech(video); vc.write_text(json.dumps(speech))
    shots = json.loads(sc.read_text()) if sc.exists() else detect_shot_changes(video); sc.write_text(json.dumps(shots))
    speech = [tuple(x) for x in speech]; shots = sorted(shots)
    vad_on = sorted(s for s, _ in speech); vad_off = sorted(e for _, e in speech)
    speak = [e for e in truth if not is_sfx(e)]
    rows = []
    for k, e in enumerate(speak):
        on = nearest(vad_on, e.start_ms); off = nearest(vad_off, e.end_ms)
        if on is None or off is None: continue
        d_in = e.start_ms - on; d_out = e.end_ms - off
        if abs(d_in) > 1000 or abs(d_out) > 1000: continue
        i = bisect.bisect_right(vad_on, off); next_vad = vad_on[i] - off if i < len(vad_on) else 10**9
        tgap = speak[k+1].start_ms - e.end_ms if k+1 < len(speak) else 10**9
        pgap = e.start_ms - speak[k-1].end_ms if k > 0 else 10**9
        s_off = nearest(shots, e.end_ms); s_on = nearest(shots, e.start_ms)
        rows.append(dict(ep=ep, d_in=d_in, d_out=d_out, next_vad=next_vad, tgap=tgap, pgap=pgap,
                         seg=(e.end_ms - d_out) - (e.start_ms - d_in), dur=e.end_ms - e.start_ms,
                         chars=len(re.sub(r"<[^>]+>", "", e.text).replace("\n", "")),
                         shot_out=(s_off - e.end_ms) if s_off is not None and abs(s_off - e.end_ms) <= 500 else None,
                         shot_in=(s_on - e.start_ms) if s_on is not None and abs(s_on - e.start_ms) <= 500 else None,
                         frame=frame))
    allrows += rows
    print(f"\n== ITV {ep} ({fps}fps): 말 자막 {len(speak)}/{len(truth)}, VAD {len(vad_on)}, 전환 {len(shots)}, 짝 {len(rows)}")
    print("  " + q([r["d_in"] for r in rows], "인점 정답-VAD온셋"))
    print("  " + q([r["d_out"] for r in rows if r["tgap"] > 200], "아웃점 정답-VAD오프 (정답 떨어짐)"))
    print("  " + q([r["d_out"] for r in rows if r["tgap"] <= 200], "아웃점 정답-VAD오프 (정답 붙음)"))
    ch = [r for r in rows if r["tgap"] <= 200]; de = [r for r in rows if r["tgap"] > 200]
    if ch and de:
        print(f"  붙임 문턱: 정답 붙은 자막의 다음 VAD 온셋까지 침묵 p95 {sorted(r['next_vad'] for r in ch)[int(len(ch)*.95)]}ms / "
              f"떨어진 자막의 침묵<=800 비율 {sum(r['next_vad']<=800 for r in de)/len(de):.0%}, 붙은 자막의 침묵<=800 {sum(r['next_vad']<=800 for r in ch)/len(ch):.0%}")
    gaps = sorted(r["tgap"] for r in rows if r["tgap"] < 10**9)
    print(f"  정답 간격 최빈: {st.multimode(gaps)[:3]} (프레임 {frame:.1f}ms), 간격<=100ms {sum(g<=100 for g in gaps)/len(gaps):.0%}")

print("\n==== 7편 합산 (정답 떨어진 자막만, 아웃점 여유)")
de = [r for r in allrows if r["tgap"] > 200]
for lo, hi in ((0, 600), (600, 1000), (1000, 1500), (1500, 2500), (2500, 10**9)):
    sel = [r for r in de if lo < r["seg"] <= hi]
    print("  " + q([r["d_out"] for r in sel], f"말소리 {lo}~{hi}") + (f"  정답 표시시간 중앙 {st.median(r['dur'] for r in sel):.0f}" if sel else ""))
alld = sorted(r["dur"] for r in allrows); short = sorted(r["dur"] for r in allrows if r["chars"] <= 12)
print(f"  표시시간 p1 {alld[len(alld)//100]} p5 {alld[len(alld)//20]} p10 {alld[len(alld)//10]} | ≤12자 중앙 {st.median(short):.0f} p25 {short[len(short)//4]} (n={len(short)})")
near = [r for r in de if r["shot_out"] is not None]
snap = [r for r in near if abs(r["shot_out"] - 2 * r["frame"]) <= r["frame"]]
snap0 = [r for r in near if abs(r["shot_out"]) <= r["frame"]]
print(f"  장면전환 근처(±500) 떨어진 아웃점 {len(near)}/{len(de)}: 전환-2프레임 {len(snap)}개, 전환 딱 {len(snap0)}개, 전환 뒤로 넘김 {sum(r['shot_out']<0 for r in near)}개")
print("  " + q([r["d_out"] for r in de if r["shot_out"] is None and r["seg"] > 1000], "전환 멀고 말>1초 아웃점 여유"))
print("  " + q([r["d_in"] for r in allrows if r["shot_in"] is None], "전환 먼 인점"))
print("  " + q([r["d_in"] for r in allrows if r["shot_in"] is not None], "전환 근처 인점"))
(OUT / "rows.json").write_text(json.dumps(allrows), encoding="utf-8")
