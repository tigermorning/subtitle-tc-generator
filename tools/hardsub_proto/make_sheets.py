"""하드섭 구간마다 대표 프레임의 자막 띠를 잘라 시트로 묶는다(화면 직접 읽기용). 시제품.

사용: python make_sheets.py VIDEO PIXEL.srt OUTDIR [PER_SHEET=8]
  OUTDIR/crops/NNNN.png   구간별 자막 띠(가운데 75%)
  OUTDIR/sheet_SSS.png    PER_SHEET개를 세로로 쌓은 시트. 왼쪽에 자막 번호와 시각을 적는다
  OUTDIR/index.json       [[번호, 시작초, 끝초, 시트번호], ...]
대표 프레임은 구간의 35% 지점이다(hardsub_tc.py는 1/4~1/2 지점).
"""
import json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
import cv2
import numpy as np

video, srt, out = sys.argv[1], sys.argv[2], sys.argv[3]
PER = int(sys.argv[4]) if len(sys.argv) > 4 else 8
TOP, BOT, X0, X1 = 0.79, 0.955, 0.125, 0.875     # hardsub_tc.py와 같은 띠
os.makedirs(f"{out}/crops", exist_ok=True)

def parse(ts):
    h, m, s, ms = map(int, re.findall(r"\d+", ts))
    return h * 3600 + m * 60 + s + ms / 1000

cues = []
for b in open(srt, encoding="utf-8").read().strip().split("\n\n"):
    L = b.split("\n")
    a, e = [parse(x) for x in L[1].split(" --> ")]
    cues.append((int(L[0]), a, e))

W, H = map(int, subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
     "-of", "csv=p=0:s=x", video], capture_output=True, text=True).stdout.strip().split("x"))
y0, bh = int(H * TOP) // 2 * 2, (int(H * BOT) - int(H * TOP)) // 2 * 2
x0, cw = int(W * X0) // 2 * 2, (int(W * X1) - int(W * X0)) // 2 * 2

def grab(c):
    n, a, e = c
    path = f"{out}/crops/{n:04d}.png"
    if os.path.exists(path):
        return
    t = a + 0.35 * (e - a)
    subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                    "-vf", f"crop={cw}:{bh}:{x0}:{y0}", "-y", path], check=True)

with ThreadPoolExecutor(6) as ex:
    list(ex.map(grab, cues))

MARGIN = 150
index = []
for s in range(0, len(cues), PER):
    rows = []
    for n, a, e in cues[s:s + PER]:
        img = cv2.imread(f"{out}/crops/{n:04d}.png")
        pad = np.full((img.shape[0], MARGIN, 3), 40, np.uint8)
        cv2.putText(pad, f"#{n}", (6, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
        cv2.putText(pad, f"{int(a)//60}:{a%60:04.1f}", (6, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        row = np.hstack([pad, img])
        rows.append(row)
        rows.append(np.full((4, row.shape[1], 3), 0, np.uint8))
        rows.append(np.full((2, row.shape[1], 3), 90, np.uint8))
        index.append([n, a, e, s // PER + 1])
    cv2.imwrite(f"{out}/sheet_{s // PER + 1:03d}.png", np.vstack(rows))
json.dump(index, open(f"{out}/index.json", "w"))
print(f"{len(cues)} crops, {(len(cues) + PER - 1) // PER} sheets -> {out}")
