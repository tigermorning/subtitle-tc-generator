"""장면전환 시각(ms) 목록을 JSON으로 저장한다. `checker.media.detect_shot_changes`(민감도 0.2, SE와 같은 ffmpeg 필터)를 그대로 쓴다.

사용(리포 루트에서): python tools/hardsub_proto/shots.py VIDEO OUT.json
71분 720p 영상에 약 45초.
"""
import json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from checker.media import detect_shot_changes

video, out = Path(sys.argv[1]), sys.argv[2]
t0 = time.time()
shots = detect_shot_changes(video, 0.2)
json.dump(shots, open(out, "w"))
print(len(shots), "shot changes", round(time.time() - t0), "s ->", out)
