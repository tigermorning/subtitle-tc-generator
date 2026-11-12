"""파형 TC(wave_tc.py 결과)에 대본 줄을 넣고, 글자 수가 넘치면 쉼에서 나눈다.

사용: python fill_script.py WAVE_TC.json SE_WAVEFORM.wav SCRIPT.txt TIMED_REF.srt OFFSET_SEC FPS GAP_FRAMES MAX_CHARS OUT.srt
- 의미는 보지 않는다. 대본 줄이 *언제* 나오는지는 시각이 있는 참고 자막(영상 안 자막 트랙 등)에서
  같은 문장(유사도 0.8 이상)을 찾아 얻는다. 대괄호 소리 표기([giggles])는 뺀다(영상 번역 자막).
- 한 자막의 대본이 MAX_CHARS 를 넘으면 그 안의 쉼(파형) 가운데 대본 줄 경계와 가장 가까운 곳에서 나누고,
  나눈 조각의 인점·아웃점을 같은 규칙(인점 0.1초 전, 아웃점 0.2~0.3초 뒤, 다음 인점 우선)으로 다시 잡는다.
"""
import sys, json, re, wave, difflib
import numpy as np

tcj, wf, script, ref, offset, fps, gap_f, max_chars, dst = sys.argv[1:10]
offset, fps, gap_f, max_chars = float(offset), eval(fps), int(gap_f), int(max_chars)
data = json.load(open(tcj, encoding="utf-8"))
thr = data["threshold_db"]

with wave.open(wf) as w:
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels()) / 32768
db = 20 * np.log10(np.abs(x).max(1) + 1e-6); dt = 1 / sr
quiet = db < thr - 15


def clean(s):
    s = re.sub(r"\[[^\]]*\]", "", s).replace("♪", "")
    return re.sub(r"\s+", " ", s).strip(" -")


def secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


refs = [(secs(*b[:4]) - offset, secs(*b[4:8]) - offset, clean(b[8].replace("\n", " ")))
        for b in re.findall(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)\n(.*?)(?:\n\n|\Z)",
                            open(ref, encoding="utf-8-sig").read(), re.S)]
clip_len = len(db) * dt
refs = [r for r in refs if -1 < r[0] < clip_len + 1 and r[2]]
lines = [clean(l) for l in open(script, encoding="utf-8-sig")]
lines = [l for l in lines if l]

# 대본 줄 -> 시각: 참고 자막을 차례로 따라가며 같은 문장을 찾는다(한 참고 줄에 대본 줄이 둘 들어 있을 수 있음)
placed, li = [], 0
pieces = {}  # 대본 줄 번호 -> 참고 자막 조각들
norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower())
for r0, r1, rt in refs:
    best = None
    for j in range(li, min(li + 400, len(lines))):
        if len(norm(lines[j])) >= 8 and norm(lines[j]) in norm(rt) or difflib.SequenceMatcher(None, norm(lines[j]), norm(rt)).ratio() > 0.8:
            best = j; break
    if best is None:
        # 참고 줄이 대본 한 줄의 «일부»면(자막 트랙이 긴 대본 줄을 여러 줄로 나눔) 그 대본 줄로 짝짓고,
        # 이어지는 조각은 시각만 이어 붙인다(대사가 통째로 빠지던 문제, 2026-11-12 전수조사)
        part_j = next((j for j in range(max(0, li - 1), min(li + 4, len(lines)))
                       if len(norm(rt)) >= 12 and norm(rt) in norm(lines[j]) and len(norm(lines[j])) > len(norm(rt)) + 3), None)
        if part_j is not None:
            pieces.setdefault(part_j, []).append((r0, r1, rt))
            if not (placed and placed[-1][3] == part_j):
                placed.append((r0, r1, lines[part_j], part_j))
            li = part_j + 1
            continue
        # 짝을 못 찾은 참고 줄은 버린다. 자막 글자는 대본 원문만 쓴다(사용자 2026-11-12 전수조사:
        # 참고 자막에만 있는 짧은 줄이 들어가 대본 줄이 밀려났다). 참고 자막은 시각을 얻는 데만 쓴다.
        continue
    # 참고 줄 하나에 이어지는 대본 줄들이 함께 들어 있으면 모두 같은 시각으로
    j = best; parts = []
    while j < len(lines) and ((len(norm(lines[j])) >= 8 and norm(lines[j]) in norm(rt)) or difflib.SequenceMatcher(None, norm(lines[j]), norm(rt)).ratio() > 0.8):
        parts.append(lines[j]); j += 1
        if difflib.SequenceMatcher(None, norm(" ".join(parts)), norm(rt)).ratio() > 0.95:
            break
    n = len(parts); span = (r1 - r0) / n
    for k, p in enumerate(parts):
        placed.append((r0 + k * span, r0 + (k + 1) * span, p, best + k))
    li = j

# 참고 자막이 대본 한 줄을 여러 조각으로 나눴으면, 대본 원문을 조각 글자 수 비율로 끊어
# 조각마다 따로 놓는다(문장부호·띄어쓰기 자리에서). 한 줄이 최대 글자를 넘을 때 나눌 수 있게 한다.
def _split_line(text, parts):
    total = sum(len(norm(p[2])) for p in parts) or 1
    out, pos = [], 0
    for k, (r0, r1, rt) in enumerate(parts):
        if k == len(parts) - 1:
            out.append((r0, r1, text[pos:].strip())); break
        target = pos + round(len(text) * len(norm(rt)) / total)
        cands = [m.end() for m in re.finditer(r"[,….!?]\s+|\s+", text) if m.end() > pos]
        cut = min(cands, key=lambda c: (abs(c - target) - (3 if text[c - 2:c - 1] in ",….!?" else 0))) if cands else len(text)
        out.append((r0, r1, text[pos:cut].strip())); pos = cut
    return [x for x in out if x[2]]
new_placed = []
for p0, p1, txt, j in placed:
    if j in pieces and len(pieces[j]) > 1:
        new_placed += [(a, b, t, j) for a, b, t in _split_line(txt, pieces[j])]
    else:
        new_placed.append((p0, p1, txt, j))
placed = new_placed
cues = data["cues"]
import os
MIN_DUR = float(os.environ.get('WAVE_TC_MIN_DUR', '0.834'))  # 넷플릭스 0.833초
# SDH 참고 자막(선택, 11번째 인자): 대괄호 소리 표기만 있는 줄([sobs, blows nose])의 시간 안에 절반 이상 들어가는
# 소리 조각은 비음성으로 보고 버린다(사용자 2026-11-12: «I do» 뒤 흐느낌·코 풀기가 대사에 붙음 — VAD 확률 0.46~0.93이라 못 거름)
dropped_sdh = []
if len(sys.argv) > 10:
    sounds = []
    for b in re.findall(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)\n(.*?)(?:\n\n|\Z)",
                        open(sys.argv[10], encoding="utf-8-sig").read(), re.S):
        txt = re.sub(r"<[^>]+>", "", b[8]).replace("\n", " ").strip()
        if txt and not re.sub(r"\[[^\]]*\]|[♪\s-]", "", txt):  # 대괄호 표기·♪만 있는 줄
            sounds.append((secs(*b[:4]) - offset, secs(*b[4:8]) - offset))
    keep_c = []
    for c in cues:
        a, b = c["voice"]
        inside = sum(max(0, min(b, s1) - max(a, s0)) for s0, s1 in sounds)
        (dropped_sdh if b > a and inside / (b - a) >= 0.5 else keep_c).append(c)
    cues = keep_c
    # 조각의 앞뒤 끝이 소리 표기 시간과 겹치면 그 부분을 잘라내고 인점·아웃점을 다시 잡는다
    for c in cues:
        a, b = c["voice"]
        def _dip(t):  # 소리 표기 시각(대략값) ±0.3초 안에서 파형이 가장 낮게 꺼지는 자리 — 경계는 파형으로 정한다
            lo, hi = max(0, int((t - 0.3) / dt)), min(len(db) - 1, int((t + 0.3) / dt))
            return (lo + int(np.argmin(db[lo:hi + 1]))) * dt if hi > lo else t
        for s0, s1 in sounds:
            if s0 <= a < s1 < b:   # 앞 끝이 소리 표기 안
                a = max(a, _dip(s1))
            if a < s0 < b <= s1:   # 뒤 끝이 소리 표기 안
                b = min(b, _dip(s0))
        if [a, b] != c["voice"]:
            # 소리 표기 시각은 자막용 대략값이다 → 자른 범위 안에서 SE 화면에 보이는 소리의 첫·마지막 자리로 다시 맞춘다
            vis = np.percentile(db, 99) - 25
            big = np.flatnonzero(db[int(a / dt):max(int(a / dt) + 1, int(b / dt))] > vis)
            if len(big):
                a, b = int(a / dt) * dt + big[0] * dt, int(a / dt) * dt + (big[-1] + 1) * dt
        if [a, b] != c["voice"] and b - a >= 0.12:
            c["voice"] = [round(a, 3), round(b, 3)]
            c["in"] = max(0, int(np.ceil((a - 0.1) * fps - 1e-9)))
            c["out"] = max(int(np.ceil((b + 0.25) * fps - 1e-9)), c["in"] + int(np.ceil(MIN_DUR * fps)))
            c["sdh_trimmed"] = True
for c in cues:
    c["text"] = []
unplaced = []
for p0, p1, txt, _ in placed:
    mid = (p0 + p1) / 2
    best, bd = None, 1e9
    for c in cues:
        a, b = c["in"] / fps, c["out"] / fps
        d = 0 if a <= mid <= b else min(abs(mid - a), abs(mid - b))
        if d < bd:
            best, bd = c, d
    if not (0 <= mid <= clip_len):  # 구간 밖 대사(앞뒤 구간 경계)는 넣지 않는다
        continue
    if best is None or bd > 1.5:
        unplaced.append((round(p0, 2), txt)); continue
    best["text"].append((p0, txt, p1))

# 대본이 없는 조각이 바로 옆(1초 안) 자막의 대본 줄 시각 범위 안에 있으면 그 자막에 합친다
# (한 문장이 짧은 쉼으로 두 조각이 되고 대본은 한쪽에만 들어간 경우)
changed = True
while changed:
    changed = False
    for k, c in enumerate(cues):
        if c["text"]:
            continue
        ca, cb = c["in"] / fps, c["out"] / fps
        for nb in (k + 1, k - 1):
            if not (0 <= nb < len(cues)) or not cues[nb]["text"]:
                continue
            o = cues[nb]
            near = (o["in"] / fps - cb) <= 1.0 if nb > k else (ca - o["out"] / fps) <= 1.0
            if near and any(t[0] <= c["voice"][1] and t[2] >= c["voice"][0] for t in o["text"]):
                o["voice"] = [min(o["voice"][0], c["voice"][0]), max(o["voice"][1], c["voice"][1])]
                o["in"], o["out"] = min(o["in"], c["in"]), max(o["out"], c["out"])
                cues.pop(k); changed = True
                break
        if changed:
            break


def frames_in(a):
    return max(0, int(np.ceil((a - 0.1) * fps - 1e-9)))


def frames_out(b):
    return int(np.ceil((b + 0.25) * fps - 1e-9))  # 음성 끝 후 0.25~0.3초


# 대본이 없는 자막은 지운다(사용자 2026-11-12: 영상 번역 자막에서 웃음·숨소리 자리). 지운 뒤 아웃점은 규칙대로 다시 잡는다
dropped = [c for c in cues if not c["text"]]
cues = [c for c in cues if c["text"]]
for c in cues:
    c["out"] = max(frames_out(c["voice"][1]), c["in"] + int(np.ceil(MIN_DUR * fps)))
out = []
for c in cues:
    texts = sorted(c["text"])
    va, vb = c["voice"]
    chunks, cur = [], []
    for t in texts:
        # 글자 수가 넘치거나, 자막이 7초(넷플릭스 최대 표시 시간)를 넘으면 대본 줄 경계에서 나눈다(사용자 2026-11-12)
        too_long = (c["out"] - c["in"]) / fps > 7.0 and (t[2] - cur[0][0] > 7.0 if cur else False)
        if cur and (len(" ".join(x[1] for x in cur + [t])) > max_chars or too_long):
            chunks.append(cur); cur = []
        cur.append(t)
    if cur:
        chunks.append(cur)
    if len(chunks) <= 1:
        out.append(dict(c, text=" ".join(x[1] for x in texts) or "(대본 없음)", split=False)); continue
    # 쉼 목록(음성 구간 안, 0.08초 이상 조용한 곳)
    i0, i1 = int(va / dt), int(vb / dt)
    gaps, k = [], i0
    while k < i1:
        if quiet[k]:
            m = k
            while m < i1 and quiet[m]:
                m += 1
            if (m - k) * dt >= 0.08:
                gaps.append((k * dt, m * dt))
            k = m
        else:
            k += 1
    bounds = [va]
    ends = []
    for ch in chunks[1:]:
        target = ch[0][0]
        cand = [g for g in gaps if bounds[-1] < g[0] and abs((g[0] + g[1]) / 2 - target) <= 1.0]
        if cand:
            g = min(cand, key=lambda g: abs((g[0] + g[1]) / 2 - target))
        else:
            # 조용한 틈이 없으면(쉬지 않고 외치는 장면) 대본 줄 경계 ±0.5초 안에서 소리가 가장 작은 지점
            lo = max(int((target - 0.5) / dt), int(bounds[-1] / dt) + 1)
            hi = min(int((target + 0.5) / dt), i1 - 1)
            if hi <= lo:
                continue
            m = lo + int(np.argmin(db[lo:hi]))
            g = (m * dt, m * dt)
        ends.append(g[0]); bounds.append(g[1])
    ends.append(vb)
    for n_, (a, b) in enumerate(zip(bounds, ends)):
        txt = " ".join(x[1] for x in chunks[n_]) if n_ < len(chunks) else ""
        if n_ == len(bounds) - 1 and len(chunks) > len(bounds):
            txt = " ".join(x[1] for ch in chunks[n_:] for x in ch)
        out.append({"voice": [round(a, 3), round(b, 3)], "in": frames_in(a), "out": frames_out(b), "text": txt, "split": True})

for k, c in enumerate(out):  # 다음 인점 우선
    if k + 1 < len(out) and c["out"] > out[k + 1]["in"] - gap_f:
        c["out"] = out[k + 1]["in"] - gap_f


def ts(f):
    t = f / fps + 0
    h, m = divmod(int(t), 3600); m, s = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{int(round((t - int(t)) * 1000)) % 1000:03d}"


with open(dst, "w", encoding="utf-8") as f:
    for k, c in enumerate(out, 1):
        f.write(f"{k}\n{ts(c['in'])} --> {ts(c['out'])}\n{c['text']}\n\n")
print(f"SDH 소리 표기 자리라 버린 조각 {len(dropped_sdh)}개: " + ", ".join(f'{d["voice"][0]:.2f}s' for d in dropped_sdh))
print(f"지운 대본 없는 자막 {len(dropped)}개: " + ", ".join(f'{d["voice"][0]:.2f}s' for d in dropped))
print(f"자막 {len(out)}개(글자 수로 나눈 조각 {sum(c['split'] for c in out)}개), 대본 없는 자막 "
      f"{sum(c['text'] == '(대본 없음)' for c in out)}개, 자리를 못 찾은 대본 줄 {len(unplaced)}개")
json.dump([[p0, p1, t] for p0, p1, t, _ in placed if any(abs(p0 - u[0]) < 0.01 and t == u[1] for u in unplaced)],
          open(dst + ".unplaced.json", "w", encoding="utf-8"), ensure_ascii=False)
for u in unplaced:
    print("  못 넣음:", u)
for k, c in enumerate(out, 1):
    if len(c["text"]) > max_chars:
        print(f"  #{k} {len(c['text'])}자 — 안에 쉼이 없어 더 못 나눔")
