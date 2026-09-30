"""우리 음성 TC 자막마다: large-v3 전사 낱말 + 시간이 겹치는 방송 화면 글자(fix7/text.srt) 를 나란히 낸다."""
import json, re, sys
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
from faster_whisper import WhisperModel
OFF = 120.0
cues = json.load(open("cues.json", encoding="utf-8"))
sr, x = wavfile.read("voice.wav"); a = resample_poly(x.astype(np.float32).mean(1) / 32768, 160, 441).astype(np.float32)
m = WhisperModel("Systran/faster-whisper-large-v3", device="cuda", compute_type="float16")
segs, _ = m.transcribe(a, language="ko", word_timestamps=True, beam_size=5, condition_on_previous_text=False, vad_filter=False)
words = [(w.start + OFF, w.end + OFF, w.word) for s in segs for w in (s.words or [])]
json.dump(words, open("words_large_v3.json", "w", encoding="utf-8"), ensure_ascii=False)
def p(ts):
    h, mi, s, ms = map(int, re.findall(r"\d+", ts)); return h*3600+mi*60+s+ms/1000
scr = []
for b in open(sys.argv[1], encoding="utf-8").read().strip().split("\n\n"):
    L = b.split("\n"); s0, e0 = [p(t) for t in L[1].split(" --> ")]
    if 118 < s0 < 242: scr.append((s0, e0, " / ".join(L[2:])))
for i, c in enumerate(cues, 1):
    ws = "".join(w[2] for w in words if c["voice_in"] - 0.15 <= w[1] - 0.05 <= c["voice_out"] + 0.15)
    sc = [f"[{s0:.2f}-{e0:.2f}] {t}" for s0, e0, t in scr if s0 < c["out"] and e0 > c["in"]]
    print(f"{i:2d} {c['in']:.3f}-{c['out']:.3f} (음성 {c['voice_in']:.2f}-{c['voice_out']:.2f})\n   전사:{ws}\n   화면: {' | '.join(sc)}")
