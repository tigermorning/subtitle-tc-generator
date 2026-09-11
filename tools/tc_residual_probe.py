"""TC 잔여 오차 측정 도구 — 정답 아웃점·인점이 어느 규칙으로 정해졌는지 갈라 본다.

2026-09-11에 드라마B E02·E03(전사 캐시 v2)으로 만든 측정 스크립트를 그대로 옮겼다
(`mfa_probe.py`처럼 경로가 박혀 있다 — 다른 작품에 쓰려면 `load()`의 경로만 바꾼다).
결과와 판단은 `docs/BACKLOG.md` §0-T "오후"·`docs/HANDOFF.md` 6절 첫 항목.

A. 생성 없이(VAD만): 정답 말 자막의 아웃점 - 가장 가까운 VAD 오프셋(부호, 양수 =
   정답이 뒤). 붙는 자막(침묵 800ms 안) / 장면전환 ±0.5초 / 말소리 길이 / 글자 수로
   갈라, 어느 규칙이 얼마나 설명하는지 본다. 이걸로 찾은 것: 짧은 말의 실무 바닥
   (약 1초, `rules/learned/*/duration_ms.짧은자막`), 전환 규칙 준수율(73~78%),
   그리고 규칙을 다 빼도 남는 아웃점 폭(사분위 +14~+197ms — 작업자 판단인지 VAD
   오프셋 오차인지는 손 라벨 없이는 못 가른다).
B. 생성 후: 우리 아웃점 - 정답(end_diff)을 진짜 짝(유사도≥0.5·정답≥8자·SFX 제외)만
   골라 떨어진/붙은으로 갈라 본다. **짧은 자막은 이 필터가 빼 버리므로** 유사도 0.7로
   따로 본다(`정답지-대조-진단` 스킬 §4 7번).

용법: python tools/tc_residual_probe.py [A|B|AB] [02 03]
중간 산출물(VAD·장면전환 캐시, 우리 초안)은 `.tmp/tc_probe/`에 남는다.
"""
import os, re, sys, bisect, json, time, statistics as st
from pathlib import Path

ROOT = Path("C:/Users/user/Documents/subtitle-tc-generator"); os.chdir(ROOT); sys.path.insert(0, str(ROOT))
from checker.parsers import parse
from checker.vad import detect_speech
from checker.timing import CHAIN_SILENCE_MS, leads_ms

SFX = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪?)\s*$")
OUT = ROOT / ".tmp" / "tc_probe"; OUT.mkdir(parents=True, exist_ok=True)

def is_sfx(e):
    lines = [l for l in e.text.split("\n") if l.strip()]
    return bool(lines) and all(SFX.match(l) for l in lines)

def nearest(vals, x):
    i = bisect.bisect_left(vals, x); c = [vals[j] for j in (i - 1, i) if 0 <= j < len(vals)]
    return min(c, key=lambda v: abs(v - x)) if c else None

def q(v, label):
    if not v:
        return f"{label}: n=0"
    a = sorted(v); n = len(a); ab = sorted(abs(x) for x in a)
    return (f"{label:22s} n={n:4d}  가운데 {st.median(a):+5.0f}ms  |중앙| {st.median(ab):4.0f}ms  "
            f"100ms안 {sum(x<=100 for x in ab)/n:4.0%}  200ms안 {sum(x<=200 for x in ab)/n:4.0%}  "
            f"사분위 {a[n//4]:+5.0f}/{a[3*n//4]:+5.0f}")

def load(ep):
    video = ROOT / f"[습작] SDH+번역/학습완료/메이드 인 코리아.Made In Korea.E{ep}.1080p.DSNP.WEB-DL.DD+-Sniper.mkv"
    truth = parse(ROOT / f"학습한 TC 및 자막 모음/디즈니플러스_메이드 인 코리아/E{ep}_한국어_SDH.srt")
    cache = OUT / f"vad_e{ep}.json"
    if cache.exists():
        speech = [tuple(x) for x in json.loads(cache.read_text())]
    else:
        speech = detect_speech(video); cache.write_text(json.dumps(speech))
    return video, truth, speech

def chained_after(vad_off, vad_on, off):
    """VAD 오프셋 off 뒤 다음 온셋이 CHAIN_SILENCE_MS 안이면 붙은 것(코드와 같은 기준)."""
    i = bisect.bisect_right(vad_on, off)
    return i < len(vad_on) and vad_on[i] - off <= CHAIN_SILENCE_MS

video_of = {}

def part_a(ep, truth, speech):
    vad_on = sorted(s for s, _ in speech); vad_off = sorted(e for _, e in speech)
    speak = [e for e in truth if not is_sfx(e)]
    print(f"\n== A. E{ep}: 정답 말 자막 {len(speak)}개, VAD 구간 {len(vad_on)}개, "
          f"CHAIN_SILENCE_MS={CHAIN_SILENCE_MS}, vad lead out={leads_ms('vad')['out']}")
    rows = []
    for k, e in enumerate(speak):
        off = nearest(vad_off, e.end_ms); on = nearest(vad_on, e.start_ms)
        if off is None or on is None: continue
        d_out = e.end_ms - off; d_in = e.start_ms - on
        if abs(d_out) > 1000 or abs(d_in) > 1000:  # 다른 구간과 짝지어진 것 — 뺀다
            continue
        nxt_truth = speak[k + 1].start_ms - e.end_ms if k + 1 < len(speak) else 10**9
        i = bisect.bisect_right(vad_on, off)
        next_vad = vad_on[i] - off if i < len(vad_on) else 10**9
        rows.append(dict(d_out=d_out, d_in=d_in, chained_vad=chained_after(vad_off, vad_on, off),
                         truth_gap=nxt_truth, end=e.end_ms, next_vad=next_vad,
                         dur=e.end_ms - e.start_ms, chars=len(e.text.replace("\n", ""))))
    print(q([r["d_in"] for r in rows], "인점 정답-VAD온셋 (전체)"))
    print("   -- 교차표: VAD 붙음 × 정답 간격")
    for cv in (False, True):
        for tg in ("<=200", ">200"):
            sel = [r["d_out"] for r in rows if r["chained_vad"] == cv and ((r["truth_gap"] <= 200) == (tg == "<=200"))]
            print("   " + q(sel, f"VAD붙음={cv!s:5s} 정답간격{tg}"))
    print("   -- 떨어진 자막(VAD 침묵>800)을 조건별로")
    det = [r for r in rows if not r["chained_vad"]]
    for lo, hi in ((800, 1200), (1200, 2000), (2000, 4000), (4000, 10**10)):
        print("   " + q([r["d_out"] for r in det if lo < r["next_vad"] <= hi], f"다음 말까지 {lo}~{hi}"))
    for lo, hi in ((0, 1000), (1000, 1500), (1500, 2500), (2500, 10**9)):
        print("   " + q([r["d_out"] for r in det if lo < r["dur"] <= hi], f"정답 표시시간 {lo}~{hi}"))
    for lo, hi in ((0, 6), (6, 12), (12, 20), (20, 99)):
        print("   " + q([r["d_out"] for r in det if lo < r["chars"] <= hi], f"정답 글자수 {lo}~{hi}"))
    # 말소리 길이(VAD 온셋~오프셋) 기준 — 정답 표시시간은 늘린 결과라 원인 쪽을 본다
    for r in det:
        r["seg"] = r["dur"] - r["d_out"] + r["d_in"]
    for lo, hi in ((0, 600), (600, 1000), (1000, 1500), (1500, 2500), (2500, 10**9)):
        sel = [r for r in det if lo < r["seg"] <= hi]
        if sel:
            durs = sorted(r["dur"] for r in sel)
            print("   " + q([r["d_out"] for r in sel], f"말소리 길이 {lo}~{hi}")
                  + f"  | 정답 표시시간 하위10% {durs[len(durs)//10]}ms 중앙 {durs[len(durs)//2]}ms")
    # 장면전환 근처 가르기 — 규칙: 아웃점은 전환 -2프레임에 붙이거나 0.5초 이상 벌림
    from checker.media import detect_shot_changes
    scache = OUT / f"shots_e{ep}.json"
    if scache.exists():
        shots = json.loads(scache.read_text())
    else:
        shots = detect_shot_changes(video_of[ep]); scache.write_text(json.dumps(shots))
    shots = sorted(shots); frame = 1000 / 23.976
    def near_shot(t):  # t가 어느 전환의 앞뒤 500ms 안인가 (부호: 전환 - t)
        s = nearest(shots, t)
        return (s - t) if s is not None and abs(s - t) <= 500 else None
    print(f"   -- 장면전환 {len(shots)}곳. 떨어진 자막을 전환 근처(정답 아웃점 ±500ms) 여부로")
    for r in det:
        r["shot_out"] = near_shot(r["end"]); r["shot_in"] = near_shot(r["end"] - r["dur"])
        vad_off_t = r["end"] - r["d_out"]
        r["shot_vad"] = near_shot(vad_off_t)  # 소리 끝이 전환 근처인가(작업자가 본 조건)
    a = [r for r in det if r["shot_vad"] is None]; b = [r for r in det if r["shot_vad"] is not None]
    print("   " + q([r["d_out"] for r in a], "소리끝 전환 멀다(>500)"))
    print("   " + q([r["d_out"] for r in b], "소리끝 전환 근처(<=500)"))
    if b:
        snapped = [r for r in b if r["shot_out"] is not None and abs(r["shot_out"] - 2 * frame) <= frame]
        print(f"      근처 {len(b)}개 중 정답 아웃점이 전환-2프레임(±1프레임)에 붙은 것 {len(snapped)}개"
              f", 전환 뒤로 넘어간 것 {sum(1 for r in b if r['shot_out'] is not None and r['shot_out'] < 0)}개")
        print("   " + q([r["d_out"] for r in snapped], "붙은 것 여유"))
    # 전환 멀고 붙지도 않은 자막 = 규칙 없는 자리 — 여기가 진짜 편차
    for lo, hi in ((0, 600), (600, 1000), (1000, 1500), (1500, 2500), (2500, 10**9)):
        sel = [r["d_out"] for r in a if lo < r["seg"] <= hi]
        print("   " + q(sel, f"전환 멀다·말소리 {lo}~{hi}"))
    aa = [r["d_out"] for r in a if r["seg"] > 1000]
    if aa:
        print(f"   전환 멀다·말>1초 여유 분포: <50 {sum(x<50 for x in aa)/len(aa):.0%}  50~100 {sum(50<=x<100 for x in aa)/len(aa):.0%}"
              f"  100~200 {sum(100<=x<=200 for x in aa)/len(aa):.0%}  200~300 {sum(200<x<=300 for x in aa)/len(aa):.0%}  >300 {sum(x>300 for x in aa)/len(aa):.0%}")
    # 인점도 같은 방식으로
    din_a = [r["d_in"] for r in rows if near_shot(r["end"] - r["dur"] - r["d_in"]) is None]
    din_b = [r["d_in"] for r in rows if near_shot(r["end"] - r["dur"] - r["d_in"]) is not None]
    print("   " + q(din_a, "인점 정답-VAD온셋 전환 멀다"))
    print("   " + q(din_b, "인점 정답-VAD온셋 전환 근처"))
    # 정답 표시시간 바닥 — 최소 노출 관행이 있으면 여기 쌓인다
    alld = sorted(r["dur"] for r in rows)
    print(f"   정답 표시시간 백분위: 1% {alld[len(alld)//100]}  5% {alld[len(alld)//20]}  10% {alld[len(alld)//10]}  25% {alld[len(alld)//4]}ms")
    # 짧은 말(<=1000ms)에서 정답 아웃점 = 온셋 + X 인지(고정 노출) / 오프셋 + Y 인지(여유)
    short = [r for r in det if r["seg"] <= 1000]
    if short:
        print("   " + q([r["dur"] for r in short], "짧은 말(<=1s) 정답 표시시간"))
        print("   " + q([r["dur"] - r["seg"] for r in short], "짧은 말 표시-말소리(앞뒤 여유 합)"))
    for name, pred in (("떨어짐(VAD 침묵>800)", lambda r: not r["chained_vad"]),
                       ("붙음(VAD 침묵<=800)", lambda r: r["chained_vad"]),
                       ("떨어짐(정답 간격>200)", lambda r: r["truth_gap"] > 200),
                       ("붙음(정답 간격<=200)", lambda r: r["truth_gap"] <= 200)):
        print(q([r["d_out"] for r in rows if pred(r)], f"아웃점 정답-VAD오프 {name}"))
    # 떨어진 자막에서 여유가 0.1~0.2초 안에 드는 비율
    det = [r["d_out"] for r in rows if not r["chained_vad"]]
    if det:
        print(f"   떨어진 자막 여유 분포: <50ms {sum(x<50 for x in det)/len(det):.0%}  "
              f"50~100 {sum(50<=x<100 for x in det)/len(det):.0%}  100~200 {sum(100<=x<=200 for x in det)/len(det):.0%}  "
              f">200 {sum(x>200 for x in det)/len(det):.0%}  <0(정답이 VAD보다 먼저 끝) {sum(x<0 for x in det)/len(det):.0%}")
    return rows

def part_b(ep, video, truth, speech):
    from checker.profile import load_profile
    from checker import genre as _genre
    from checker.generate import generate
    from checker.evaluate import compare
    profile = _genre.apply(load_profile("disney", "ko", "sdh"), "drama")
    t0 = time.time(); print(f"\n== B. E{ep}: 생성 시작 {time.strftime('%H:%M:%S')}")
    draft = generate(video, profile, language="ko", use_gpu=True,
                     transcript_cache=ROOT / f".tmp/mik_e{ep}_transcript_cache_v2.srt",
                     progress=lambda m: None)
    ours = list(draft.events)
    print(f"   생성 {time.time()-t0:.0f}초, 우리 자막 {len(ours)}개")
    from checker.writers import write_srt
    write_srt(ours, OUT / f"ours_e{ep}.srt")
    cmp = compare(ours, truth)
    vad_on = sorted(s for s, _ in speech); vad_off = sorted(e for _, e in speech)
    real = [p for p in cmp.matched if p.text_similarity is not None and p.text_similarity >= 0.5
            and len(p.truth.text.strip()) >= 8 and not is_sfx(p.truth)]
    print(f"   짝지음 {len(cmp.matched)}/{len(truth)}, 진짜 짝 {len(real)}")
    rows = []
    for p in real:
        off = nearest(vad_off, p.ours.end_ms)
        rows.append(dict(end=p.end_diff, start=p.start_diff,
                         chained=chained_after(vad_off, vad_on, off) if off is not None else None,
                         ours_minus_vad=p.ours.end_ms - off if off is not None else None))
    print(q([r["start"] for r in rows], "인점 우리-정답 (전체)"))
    print(q([r["end"] for r in rows], "아웃점 우리-정답 (전체)"))
    print(q([r["end"] for r in rows if r["chained"] is False], "아웃점 우리-정답 떨어짐"))
    print(q([r["end"] for r in rows if r["chained"] is True], "아웃점 우리-정답 붙음"))
    print(q([r["ours_minus_vad"] for r in rows if r["chained"] is False and r["ours_minus_vad"] is not None],
            "우리아웃-VAD오프 떨어짐"))
    # 진짜 짝 필터(정답>=8자)가 빼 버리는 짧은 자막 — 유사도 0.7 이상으로 따로 본다
    shortp = [p for p in cmp.matched if p.text_similarity is not None and p.text_similarity >= 0.7
              and len(p.truth.text.strip()) < 8 and not is_sfx(p.truth)]
    sh = []
    for p in shortp:
        off = nearest(vad_off, p.ours.end_ms)
        sh.append(dict(end=p.end_diff, chained=chained_after(vad_off, vad_on, off) if off is not None else None,
                       ours_dur=p.ours.duration_ms, truth_dur=p.truth.duration_ms))
    print(q([r["end"] for r in sh], "짧은정답(<8자) 아웃점 우리-정답"))
    print(q([r["end"] for r in sh if r["chained"] is False], "짧은정답 아웃점 떨어짐"))
    print(q([r["ours_dur"] for r in sh if r["chained"] is False], "짧은정답 떨어짐 우리 표시시간"))
    print(q([r["truth_dur"] for r in sh if r["chained"] is False], "짧은정답 떨어짐 정답 표시시간"))
    # 남은 왼쪽 꼬리(>=8자 떨어짐)를 말소리 길이·정답 글자수로
    det =[(p, r) for p, r in zip(real, rows) if r["chained"] is False]
    for lo, hi in ((0, 12), (12, 20), (20, 99)):
        print("   " + q([r["end"] for p, r in det if lo <= len(p.truth.text.strip()) < hi], f"떨어짐 정답 글자수 {lo}~{hi}"))
    for lo, hi in ((0, 1000), (1000, 1500), (1500, 2500), (2500, 10**9)):
        print("   " + q([r["end"] for p, r in det if lo < p.ours.duration_ms <= hi], f"떨어짐 우리 표시시간 {lo}~{hi}"))
    return rows

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "A"
    eps = sys.argv[2:] or ["02", "03"]
    for ep in eps:
        video, truth, speech = load(ep)
        video_of[ep] = video
        if "A" in mode: part_a(ep, truth, speech)
        if "B" in mode: part_b(ep, video, truth, speech)
