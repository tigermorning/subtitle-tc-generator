"""MFA(Montreal Forced Aligner) 실측 도구 — 2026-09-11 판정 근거 재현용.

인·아웃점 후보로 VAD보다 낫지 않아 **안 붙이기로 했다**(`docs/HANDOFF.md` 8절
"검토했고 안 붙이기로 한 정렬기"). 다시 재야 할 때만 쓴다.

    python tools/mfa_probe.py prep 02 03   # whisper 세그먼트마다 wav+.lab (.tmp/mfa/E??/corpus)
    # WSL(conda env mfa311):
    #   mfa align <corpus> korean_mfa korean_mfa <out> --clean --single_speaker -j 8     #       --beam 40 --retry_beam 160 --g2p_model_path korean_mfa
    #   TextGrid를 .tmp/mfa/E??/aligned/ 로 복사
    python tools/mfa_probe.py eval 02 03   # 정답 인점·아웃점 대비 VAD / whisper 단어 / MFA 단어 거리
"""
import sys

MODE = sys.argv.pop(1) if len(sys.argv) > 1 and sys.argv[1] in ("prep", "eval") else "eval"

if MODE == "prep":
    import os, re, sys, wave
    from pathlib import Path
    import numpy as np
    ROOT = Path("C:/Users/user/Documents/subtitle-tc-generator"); os.chdir(ROOT); sys.path.insert(0, str(ROOT))
    from checker.transcribe import _parse_srt
    from checker.vad import _read_audio, SAMPLE_RATE

    PAD = 300
    for ep in sys.argv[1:] or ["02", "03"]:
        video = ROOT / f"[습작] SDH+번역/학습완료/메이드 인 코리아.Made In Korea.E{ep}.1080p.DSNP.WEB-DL.DD+-Sniper.mkv"
        segs = _parse_srt((ROOT / f".tmp/mik_e{ep}_transcript_cache_v2.srt").read_text(encoding="utf-8"))
        audio = _read_audio(video)
        out = ROOT / f".tmp/mfa/E{ep}/corpus"; out.mkdir(parents=True, exist_ok=True)
        n = 0
        for i, s in enumerate(segs):
            text = re.sub(r"[^\w\s가-힣]", " ", s.text).split()
            if not text:
                continue
            a = max(0, s.start_ms - PAD); b = min(len(audio) * 1000 // SAMPLE_RATE, s.end_ms + PAD)
            clip = (audio[a * SAMPLE_RATE // 1000: b * SAMPLE_RATE // 1000] * 32767).astype(np.int16)
            name = f"seg{i:04d}_{a:08d}"
            with wave.open(str(out / f"{name}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(clip.tobytes())
            (out / f"{name}.lab").write_text(" ".join(text), encoding="utf-8")
            n += 1
        print(f"E{ep}: {n} clips -> {out}")
else:
    import os, re, sys, bisect, json, statistics as st
    from pathlib import Path
    ROOT = Path("C:/Users/user/Documents/subtitle-tc-generator"); os.chdir(ROOT); sys.path.insert(0, str(ROOT))
    from checker.parsers import parse
    from checker.vad import detect_speech

    SFX = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪?)\s*$")
    TG_INT = re.compile(r'intervals \[\d+\]:\s*xmin = ([\d.]+)\s*xmax = ([\d.]+)\s*text = "([^"]*)"', re.S)

    def textgrid_words(path: Path):
        txt = path.read_text(encoding="utf-8", errors="replace")
        # words tier = first tier; phones tier follows. Take intervals before 'name = "phones"'.
        cut = txt.find('name = "phones"')
        body = txt[:cut] if cut > 0 else txt
        return [(float(a), float(b), t) for a, b, t in TG_INT.findall(body) if t.strip()]

    def nearest_abs(vals, x):
        i = bisect.bisect_left(vals, x); c = [vals[j] for j in (i - 1, i) if 0 <= j < len(vals)]
        return min(abs(v - x) for v in c) if c else None
    def q(v):
        a = sorted(v); n = len(a)
        return f"|중앙| {st.median(a):.0f}ms  100ms안 {sum(x<=100 for x in a)/n:.0%}  200ms안 {sum(x<=200 for x in a)/n:.0%}  n={n}"

    for ep in sys.argv[1:] or ["02", "03"]:
        video = ROOT / f"[습작] SDH+번역/학습완료/메이드 인 코리아.Made In Korea.E{ep}.1080p.DSNP.WEB-DL.DD+-Sniper.mkv"
        truth = parse(ROOT / f"학습한 TC 및 자막 모음/디즈니플러스_메이드 인 코리아/E{ep}_한국어_SDH.srt")
        speak = [e for e in truth if not all(SFX.match(l) for l in e.text.split("\n") if l.strip())]
        # VAD
        speech = detect_speech(video)
        vad_on = sorted(s for s, _ in speech); vad_off = sorted(e for _, e in speech)
        # whisper words
        ww = json.loads((ROOT / f".tmp/mik_e{ep}_transcript_cache_v2.srt.words.json").read_text(encoding="utf-8"))
        w_on = sorted(w[0] for seg in ww for w in seg); w_off = sorted(w[1] for seg in ww for w in seg)
        # MFA words
        m_on, m_off, n_tg = [], [], 0
        for tg in sorted((ROOT / f".tmp/mfa/E{ep}/aligned").glob("*.TextGrid")):
            base = int(tg.stem.split("_")[1])
            words = textgrid_words(tg)
            if not words: continue
            n_tg += 1
            for a, b, _ in words:
                m_on.append(base + int(a * 1000)); m_off.append(base + int(b * 1000))
        m_on.sort(); m_off.sort()
        print(f"E{ep}: 정답 말 자막 {len(speak)}개, MFA TextGrid {n_tg}개, MFA 단어 {len(m_on)}개, whisper 단어 {len(w_on)}개, VAD 구간 {len(vad_on)}개")
        for label, on, off in (("VAD", vad_on, vad_off), ("whisper 단어", w_on, w_off), ("MFA 단어", m_on, m_off)):
            din = [nearest_abs(on, e.start_ms) for e in speak]; dout = [nearest_abs(off, e.end_ms) for e in speak]
            din = [x for x in din if x is not None]; dout = [x for x in dout if x is not None]
            print(f"   {label:12s} 인점 {q(din)} | 아웃점 {q(dout)}")
        # 정답 인점 대비 부호(여유 포함): MFA 첫 경계 - 정답
        def signed(on, x):
            i = bisect.bisect_left(on, x); c = [on[j] for j in (i - 1, i) if 0 <= j < len(on)]
            return min(c, key=lambda v: abs(v - x)) - x if c else None
        for label, on in (("VAD", vad_on), ("MFA 단어", m_on)):
            sg = [signed(on, e.start_ms) for e in speak]; sg = [x for x in sg if x is not None and abs(x) < 600]
            print(f"   {label:12s} 인점 부호 가운데 {st.median(sg):+.0f}ms (양수 = 후보가 정답보다 뒤 = 정답이 여유를 둠)")

        # 밀도 공정 비교: 세그먼트당 하나 — whisper 세그먼트 시작/끝 vs MFA 첫 단어 시작/마지막 단어 끝
        from checker.transcribe import _parse_srt
        segs = _parse_srt((ROOT / f".tmp/mik_e{ep}_transcript_cache_v2.srt").read_text(encoding="utf-8"))
        s_on = sorted(s.start_ms for s in segs); s_off = sorted(s.end_ms for s in segs)
        f_on, f_off = [], []
        for tg in sorted((ROOT / f".tmp/mfa/E{ep}/aligned").glob("*.TextGrid")):
            base = int(tg.stem.split("_")[1]); words = textgrid_words(tg)
            if words:
                f_on.append(base + int(words[0][0] * 1000)); f_off.append(base + int(words[-1][1] * 1000))
        f_on.sort(); f_off.sort()
        print(f"   -- 세그먼트당 하나(밀도 같음: whisper 세그먼트 {len(s_on)} / MFA 첫·끝 단어 {len(f_on)} / VAD {len(vad_on)})")
        for label, on, off in (("whisper 세그먼트", s_on, s_off), ("MFA 첫/끝 단어", f_on, f_off), ("VAD", vad_on, vad_off)):
            din = [x for x in (nearest_abs(on, e.start_ms) for e in speak) if x is not None]
            dout = [x for x in (nearest_abs(off, e.end_ms) for e in speak) if x is not None]
            print(f"   {label:14s} 인점 {q(din)} | 아웃점 {q(dout)}")
