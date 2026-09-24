#!/usr/bin/env bash
# 하드섭 TC 시제품 전체 파이프라인. 리포 루트에서: bash tools/hardsub_proto/run_pipeline.sh VIDEO OUTDIR [SHOTS.json]
#   1) hardsub_tc.py   픽셀 신호로 자막 구간 + 대표 프레임 OCR  -> pixel.srt          (71분 720p에 약 10~15분)
#   2) audio_snap.py   인점을 음성 시작점(±200ms)으로            -> audio.srt, onsets.json (약 1분)
#   3) shots.py        장면전환 목록(없으면 만든다)              -> shots.json          (약 45초)
#   4) tc_rules_nf.py  간격·넷플릭스 장면전환 규칙               -> final.srt, report.txt
set -euo pipefail
V="$1"; OUT="$2"; SHOTS="${3:-$OUT/shots.json}"
T="$(dirname "$0")"
mkdir -p "$OUT"
export PYTHONIOENCODING=utf-8
python "$T/hardsub_tc.py" "$V" "$OUT/pixel.srt" 2>&1 | grep -vE "Warn|Broken pipe|muxing|rawvideo|trailer|closing|Last message" | tee "$OUT/log1.txt"
python "$T/audio_snap.py" "$V" "$OUT/pixel.srt" "$OUT/audio.srt" 200 "$OUT/onsets.json" 2>&1 | tee "$OUT/log2.txt"
[ -f "$SHOTS" ] || python "$T/shots.py" "$V" "$SHOTS" 2>&1 | tee "$OUT/log3a.txt"
python "$T/tc_rules_nf.py" "$OUT/audio.srt" "$SHOTS" "$OUT/final.srt" "$OUT/report.txt" 2>&1 | tee "$OUT/log3.txt"
echo PIPELINE_DONE
