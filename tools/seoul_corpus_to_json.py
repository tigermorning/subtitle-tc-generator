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
한 덩어리로 합쳐 파일마다 `{"segments": [{"start", "end"}, ...], "exclude":
[{"from", "to"}, ...]}`(초)로 쓴다. `exclude`가 아래 인터뷰어 구간이다.
`<LAUGH-네>`처럼 웃음 섞인 말은 발화로 친다. `in_points`/`out_points`는 그중
옆에 0.4초 이상 비발화가 붙은 경계만 — `vad_sweep.py --corpus`가 인점·아웃점
오차를 잴 때 이것만 쓴다(아래 주석).

**`<IVER>`는 인터뷰어 발화다 — 소리는 있는데 라벨은 태그뿐이다.** 그래서 이
JSON의 빈자리를 "말소리 없음"으로 읽으면 안 된다. VAD 정답으로 쓸 때는 이
구간을 평가에서 **빼야** 한다 — `vad_sweep.py --corpus`가 `exclude`를 읽어 뺀다.

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

# 소리는 있는데 라벨이 태그뿐인 구간 — VAD 평가에서 **빼야** 하는 자리.
#   <IVER>         인터뷰어 발화(피험자만 전사됐다)
#   <UNKNOWN>      알아듣지 못한 말(말소리는 있다)
#   <PRIVATE.INFO> 개인정보 구간(음성이 가려졌을 수 있다)
EXCLUDE = re.compile(r"^<(IVER|UNKNOWN|PRIVATE\.INFO)>$")


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


# 경계로 셀 수 있는 자리 — 옆에 이만큼 **비발화**(<SIL>·<VOCNOISE>·<NOISE>)가
# 있어야 한다. 인터뷰어 "네"가 침묵 없이 붙는 자리는 라벨은 끊지만 소리는 이어져
# VAD가 못 끊는 것이 정상이다 — 그 경계를 오차로 세면 아웃점 오차가 초 단위로
# 부풀어 아무것도 못 읽는다(2026-09-10 2파일 실측: 아웃점 중앙 1.6초).
MIN_GAP_S = 0.4
NONSPEECH = re.compile(r"^<(SIL|VOCNOISE|NOISE)>$")


def boundaries(intervals, min_gap=MIN_GAP_S):
    """옆이 충분한 비발화인 인점·아웃점만 고른다."""
    ins, outs = [], []
    for k, (s, e, t) in enumerate(intervals):
        if not t or TAG.match(t):
            continue
        if k > 0:
            ps, pe, pt = intervals[k - 1]
            if NONSPEECH.match(pt) and pe - ps >= min_gap:
                ins.append(s)
        if k + 1 < len(intervals):
            ns, ne, nt = intervals[k + 1]
            if NONSPEECH.match(nt) and ne - ns >= min_gap:
                outs.append(e)
    return ins, outs


def excludes(intervals):
    out = []
    for s, e, t in intervals:
        if not EXCLUDE.match(t):
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
    x = excludes(utt)
    ins, outs = boundaries(utt)
    (dst / (tg.stem + ".json")).write_text(json.dumps(
        {"segments": [{"start": s, "end": e} for s, e in r],
         "exclude": [{"from": s, "to": e} for s, e in x],
         "in_points": ins, "out_points": outs}), encoding="utf-8")
    stats.append((tg.stem, len(utt), len(r)))
print(len(stats), "files; utt intervals / speech runs, first 3:", stats[:3])
