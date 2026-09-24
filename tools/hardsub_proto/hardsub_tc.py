"""하드섭 대사 자막: 한 번의 연속 디코딩으로 TC(모든 프레임) + 구간마다 대표 프레임 1장 OCR.

해상도에 비례해 띠 위치·커널·픽셀 하한을 잡는다. 시제품.
사용: python hardsub_tc.py VIDEO OUT.srt [t_end_sec] [band_top] [band_bot]
"""
import json, subprocess, sys, time, difflib
from fractions import Fraction
import numpy as np, cv2

video, out_srt = sys.argv[1], sys.argv[2]
t_end = float(sys.argv[3]) if len(sys.argv) > 3 else None
TOP = float(sys.argv[4]) if len(sys.argv) > 4 else 0.79   # 720p에서 570/720
BOT = float(sys.argv[5]) if len(sys.argv) > 5 else 0.955  # 720p에서 688/720

info = json.loads(subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
     "stream=width,height,r_frame_rate", "-of", "json", video],
    capture_output=True, text=True).stdout)["streams"][0]
W, H = info["width"], info["height"]
FPS = float(Fraction(info["r_frame_rate"]))
S = H / 720                                   # 720p 기준 배율
Y0 = int(H * TOP) // 2 * 2
BH = (int(H * BOT) - Y0) // 2 * 2
X0, X1 = int(W * 0.125), int(W * 0.875)       # OCR용 가운데만
KER = cv2.getStructuringElement(cv2.MORPH_RECT, (int(9 * S) | 1, int(9 * S) | 1))
MIN_CNT = int(500 * S * S)
SIM_CUT, MIN_LEN = 0.5, 6
MERGE_IOU = float(__import__('os').environ.get('MERGE_IOU', '0.5'))
DIL = np.ones((3, 3), np.uint8)
print(f"{W}x{H} {FPS:.3f}fps band y{Y0}+{BH} kernel {KER.shape} min_cnt {MIN_CNT}")

cmd = ["ffmpeg", "-v", "error", "-i", video]
if t_end:
    cmd += ["-t", str(t_end)]
cmd += ["-vf", f"crop={W}:{BH}:0:{Y0}", "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)
FB = W * BH * 3

segs = []          # (start, end_exclusive, 대표 crop)
cur, cur_img, next_grab = None, None, 0
acc = None
prev = None
i = 0
t0 = time.time()

def close(end):
    if end - cur >= MIN_LEN and cur_img is not None:
        segs.append((cur, end, cur_img, cv2.dilate(acc.astype(np.uint8), DIL)))

while True:
    buf = p.stdout.read(FB)
    if len(buf) < FB:
        break
    bgr = np.frombuffer(buf, np.uint8).reshape(BH, W, 3)
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    m = (cv2.morphologyEx(g, cv2.MORPH_TOPHAT, KER) > 45) & (g > 170)
    c = int(m.sum())
    sim = 0.0 if prev is None else int((m & prev[0]).sum()) / max(c, prev[1], 1)
    prev = (m, c)
    on = c >= MIN_CNT
    if cur is not None and (not on or sim < SIM_CUT):
        close(i); cur = None
    if on and cur is None:
        cur, cur_img, next_grab = i, None, i + MIN_LEN
        acc = m.copy()
    elif cur is not None and i - cur < MIN_LEN:
        acc &= m   # 첫 MIN_LEN 프레임 내내 켜진 픽셀 = 움직이는 배경이 빠진 글자 핵심
    # 대표 프레임: 시작 후 6, 12, 24, 48...번째로 갱신 - 구간의 대략 1/4~1/2 지점이 남는다
    if cur is not None and i == next_grab:
        cur_img = bgr[:, X0:X1].copy()
        next_grab = cur + 2 * (i - cur)
    i += 1
if cur is not None:
    close(i)
print(f"{i} frames, {len(segs)} segments, scan {time.time()-t0:.1f}s")

# 붙어 있는 두 구간의 글자 핵심이 겹치면 같은 자막(배경만 바뀌어 신호가 끊긴 것) - 합침
merged = []
for a, b, img, core in segs:
    if merged and a - merged[-1][1] <= 1:
        pc = merged[-1][3]
        iou = int((pc & core).sum()) / max(int((pc | core).sum()), 1)
        if iou > MERGE_IOU:
            merged[-1][1] = b
            continue
    merged.append([a, b, img, core])
print(f"core merge: {len(segs)} -> {len(merged)}")
segs = merged

import easyocr
reader = easyocr.Reader(["ko"], gpu=True, verbose=False)
t0 = time.time()
texts = []
for _a, _b, img, _c in segs:
    res = reader.readtext(img, detail=1, paragraph=False)
    res = [r for r in res if r[2] >= 0.3] or res   # 전부 낮으면 버리지 말고 그대로 (사람 확인용)
    rows = []   # 세로 중심이 가까운 상자끼리 한 줄, 줄 안에서는 왼쪽부터
    for box, t, conf in sorted(res, key=lambda r: (r[0][0][1] + r[0][2][1]) / 2):
        yc = (box[0][1] + box[2][1]) / 2
        if rows and abs(yc - rows[-1][0]) < 15 * S:
            rows[-1][1].append((box[0][0], t))
        else:
            rows.append([yc, [(box[0][0], t)]])
    texts.append("\n".join(" ".join(t for _x, t in sorted(r[1])) for r in rows).strip())
print(f"ocr {time.time()-t0:.1f}s")

cues = []
for (a, b, _img, _c), t in zip(segs, texts):
    t = t or "[읽기 실패]"   # 신호는 글자라는데 OCR이 비었다 - 버리지 않고 사람이 보게 남김
    if cues and a - cues[-1][1] <= 1 and difflib.SequenceMatcher(None, cues[-1][2], t).ratio() > 0.8:
        cues[-1][1] = b   # 자막 뒤 화면 전환으로 갈린 같은 자막은 합침
    else:
        cues.append([a, b, t])

def tc(f):
    # 프레임 시각을 10ms 단위로 내림: SE 미리보기(ASS, 10ms 반올림)에서도 pts(f-1) < T <= pts(f)가 유지된다
    ms = int(f / FPS * 100) * 10
    return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"

with open(out_srt, "w", encoding="utf-8") as f:
    for n, (a, b, t) in enumerate(cues, 1):
        f.write(f"{n}\n{tc(a)} --> {tc(b)}\n{t}\n\n")
print(len(cues), "cues ->", out_srt)
