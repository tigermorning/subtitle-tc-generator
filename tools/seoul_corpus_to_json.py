"""Seoul Corpus(OpenSLR 113) TextGrid -> `tools/timestamp_origin.py`가 읽는 {start,end} JSON.

## 왜 있나

`checker/vad.py`의 한국어 실사 lane 근거가 한 작품(드라마B)뿐이라
규칙 12의 "최소 2편"에 못 닿아 있다. Seoul Corpus는 한국어 즉흥 발화 27시간을
HTK로 정렬한 뒤 **사람이 손보정**한 경계(Praat TextGrid)라 그 빈칸의 후보다.
2026-09-10 `timestamp_origin.py`로 240파일 전부 재서 자동 지문 0(이어붙임
0.0%, 격자 쏠림 없음, 길이 상한 봉우리 없음)을 확인했다 — `docs/HANDOFF.md`
8절.

## 무엇을 내나

`utt.ortho.` 티어(발화 단위)에서 태그 구간(`<SIL>` `<IVER>` `<VOCNOISE>`
`<NOISE>` `<UNKNOWN>` `<PRIVATE.INFO>` `<LAUGH>`)을 빼고, 서로 맞닿은 발화를
한 덩어리로 합쳐 파일마다 `{"segments": [{"start", "end"}, ...]}`(초)로 쓴다.
`<LAUGH-네>`처럼 웃음 섞인 말은 발화로 친다.

**`<IVER>`는 인터뷰어 발화다 — 소리는 있는데 라벨은 태그뿐이다.** 그래서 이
JSON의 빈자리를 "말소리 없음"으로 읽으면 안 된다. VAD 정답으로 쓸 때는 이
구간을 평가에서 **빼야** 한다(`vad_sweep.py`에 아직 그 기능이 없다).

    python tools/seoul_corpus_to_json.py <TextGrid 폴더> <출력 폴더>
"""
import json, re, sys
from pathlib import Path

TAG = re.compile(r"^<(SIL|IVER|VOCNOISE|NOISE|UNKNOWN|PRIVATE\.INFO|LAUGH)>$")

def parse(path):
    txt = path.read_text(encoding="utf-16")
    tiers = {}
    cur = None
    it = iter(txt.splitlines())
    for line in it:
        line = line.strip()
        m = re.match(r'name = "(.*)"', line)
        if m:
            cur = m.group(1); tiers.setdefault(cur, [])
            continue
        if line.startswith("xmin = ") and cur is not None:
            xmin = float(line.split("=")[1])
            xmax = float(next(it).strip().split("=")[1])
            text = next(it).strip().split("=", 1)[1].strip().strip('"')
            tiers[cur].append((xmin, xmax, text))
    return tiers

def runs(intervals):
    out = []
    for s, e, t in intervals:
        if not t or TAG.match(t):
            continue
        if out and abs(out[-1][1] - s) < 1e-6:
            out[-1][1] = e
        else:
            out.append([s, e])
    return out

src = Path(sys.argv[1]); dst = Path(sys.argv[2]); dst.mkdir(exist_ok=True)
stats = []
for tg in sorted(src.glob("s*.TextGrid")):
    tiers = parse(tg)
    # 티어 머리(xmin/xmax/intervals: size)가 첫 항목으로 섞여 들어온다 — 버린다.
    utt = [(s, e, t) for s, e, t in tiers["utt.ortho."] if not t.startswith("intervals")][1:]
    r = runs(utt)
    (dst / (tg.stem + ".json")).write_text(json.dumps(
        {"segments": [{"start": s, "end": e} for s, e in r]}), encoding="utf-8")
    stats.append((tg.stem, len(utt), len(r)))
print(len(stats), "files; utt intervals / speech runs, first 3:", stats[:3])
