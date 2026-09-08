"""`vad.detect_speech()`의 문턱값 셋이 실제로 어떤 값인지 재 본다.

## 왜 필요한가

`checker/vad.py`의 기본값 셋 — `threshold=0.5`, `min_speech_ms=120`,
`min_silence_ms=250` — 은 **근거가 어디에도 안 적혀 있다.** VAD를 들인 커밋
(`3e49433`, 2026-08-11)은 "음량 검출 대 Silero VAD"는 4편으로 재서 기록했지만,
이 세 값 자체를 무엇과 견줘 정했는지는 남기지 않았다. 규칙 11이 말하는 "규정이
비워 둔 자리를 코드가 채운 것"인데, 그 채운 값의 출처가 없는 상태다.

이 도구는 값을 **고르지 않는다.** 정답지와 견줘 숫자를 내놓기만 한다. 어느 값을
쓸지는 사람이 정한다(규칙 11의 승격 경로와 같다 — 관측이 곧 규정이 되지 않는다).

## 어떻게 재나

정답 자막의 인점·아웃점을 기준으로 본다. 말소리 구간이 자막 경계와 얼마나
가까운지가 스포팅 제안의 품질을 그대로 좌우한다.

    덮음        정답 자막 중 말소리 구간과 겹치는 비율 (못 덮으면 스포팅을 못 한다)
    인점 오차   자막 시작과 가장 가까운 구간 시작의 거리 (중앙값·95%)
    아웃점 오차 자막 끝과 가장 가까운 구간 끝의 거리
    구간 수     너무 잘게 쪼개지면(수가 크면) 경계가 아무 데나 맞아 오차가 낮아 보인다

**추론은 한 번만 돌린다.** 확률 열(`_probabilities`)을 구해 놓고 문턱값만 바꿔
가며 구간을 다시 만든다 — `vad.py`가 그 함수를 따로 뺀 이유가 이것이다.

## 한계 — 이 숫자로 규정을 바꾸지 않는다

- SDH 정답지에는 효과음·음악 자막이 섞여 있다. 대괄호·음표만 있는 자막은 빼지만,
  화면 밖 소리를 적은 자막까지 다 걸러내지는 못한다.
- 원어가 한국어가 아닌 작품에서는 번역 자막의 경계가 원어 발화와 조금 어긋난다.
- **한 작품만으로는 아무것도 정하지 않는다**(규칙 12 — 최소 2편).

    python tools/vad_sweep.py --video <mkv> --truth <정답.srt>
"""

from __future__ import annotations

import argparse
import re
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from checker.parsers import parse  # noqa: E402
from checker.vad import (SAMPLE_RATE, VadUnavailable, _probabilities,  # noqa: E402
                         _read_audio, _spans, find_model)

# 대괄호·음표만 있는 자막은 사람 말이 아니다. 효과음·음악 표기라 VAD가 못 잡는
# 것이 정상이고, 그것을 오차로 세면 문턱값이 엉뚱하게 낮은 쪽으로 끌린다.
_NON_SPEECH = re.compile(r"^\s*(?:\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪?|-)\s*$")

GRID_THRESHOLD = (0.3, 0.4, 0.5, 0.6, 0.7)
GRID_MIN_SPEECH = (80, 120, 200, 250)
GRID_MIN_SILENCE = (100, 250, 400)
CURRENT = (0.5, 120, 250)   # 지금 `vad.detect_speech()`의 기본값


def speech_cues(path: Path):
    """정답 자막에서 **사람 말인 자막만** 남긴다."""
    out = []
    for ev in parse(path):
        lines = [ln for ln in ev.text.split("\n") if ln.strip()]
        if not lines or all(_NON_SPEECH.match(ln) for ln in lines):
            continue
        out.append((ev.start_ms, ev.end_ms))
    return out


def score(spans, cues) -> dict:
    """구간과 정답 자막을 견준다. 값이 작을수록 좋다(덮음만 클수록 좋다)."""
    if not spans or not cues:
        return {}
    starts = [s for s, _ in spans]
    ends = [e for _, e in spans]
    in_err, out_err, covered = [], [], 0
    for cue_start, cue_end in cues:
        in_err.append(min(abs(s - cue_start) for s in starts))
        out_err.append(min(abs(e - cue_end) for e in ends))
        if any(s < cue_end and e > cue_start for s, e in spans):
            covered += 1

    def p95(values):
        return round(st.quantiles(values, n=100)[94]) if len(values) > 2 else None

    return {"구간": len(spans), "덮음%": round(100 * covered / len(cues), 1),
            "인점중앙": round(st.median(in_err)), "인점95": p95(in_err),
            "아웃중앙": round(st.median(out_err)), "아웃95": p95(out_err)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--truth", type=Path, required=True, help="정답 자막(.srt)")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()

    cues = speech_cues(a.truth)
    if not cues:
        print("정답 자막에 사람 말 자막이 없습니다.", file=sys.stderr)
        return 2

    started = time.time()
    try:
        model_path = find_model(a.model)
    except VadUnavailable as exc:
        print(f"{exc}", file=sys.stderr)
        return 2
    audio = _read_audio(a.video)
    total_ms = int(len(audio) / SAMPLE_RATE * 1000)
    print(f"{a.video.name}: 오디오 {total_ms / 60000:.1f}분, 정답 말자막 {len(cues)}개",
          file=sys.stderr)
    probabilities = _probabilities(audio, model_path)
    print(f"  추론 {time.time() - started:.0f}초 — 이제 문턱값만 바꿔 가며 잽니다",
          file=sys.stderr)

    rows = []
    for threshold in GRID_THRESHOLD:
        for min_speech in GRID_MIN_SPEECH:
            for min_silence in GRID_MIN_SILENCE:
                spans = _spans(probabilities, threshold, min_speech, min_silence,
                               0, total_ms)
                got = score(spans, cues)
                if got:
                    rows.append(((threshold, min_speech, min_silence), got))

    print(f"\n{'문턱':>5} {'말최소':>6} {'침묵최소':>8} │ "
          f"{'구간':>6} {'덮음%':>6} {'인점중앙':>8} {'인점95':>7} "
          f"{'아웃중앙':>8} {'아웃95':>7}")
    for params, got in sorted(rows, key=lambda r: (r[1]["인점중앙"] + r[1]["아웃중앙"])):
        mark = " <- 지금 값" if params == CURRENT else ""
        print(f"{params[0]:>5} {params[1]:>6} {params[2]:>8} │ "
              f"{got['구간']:>6} {got['덮음%']:>6} {got['인점중앙']:>8} "
              f"{got['인점95']:>7} {got['아웃중앙']:>8} {got['아웃95']:>7}{mark}")
    print("\n한 작품으로는 아무것도 정하지 않는다(규칙 12 — 최소 2편). "
          "구간 수가 크게 늘면 오차가 낮아 보이는 것이 당연하다는 점도 함께 본다.")

    # `resplit._snap_to_silence(tolerance_ms=400)`도 근거가 안 적힌 값이다. 그
    # 함수는 **자를 자리를 가까운 침묵 한가운데로 당기는데**, 얼마나 멀리까지
    # 당겨야 하는지가 이 값이다. 정답 자막의 경계가 실제로 침묵 한가운데에서
    # 얼마나 떨어져 있는지를 재면 그 폭을 자료로 말할 수 있다.
    spans = _spans(probabilities, *CURRENT, 0, total_ms)
    middles = [(a_end + b_start) // 2 for (_, a_end), (b_start, _) in
               zip(spans, spans[1:])]
    if middles:
        distances = sorted(min(abs(m - b) for m in middles)
                           for cue in cues for b in cue)
        def pct(p):
            return distances[min(len(distances) - 1, int(len(distances) * p / 100))]
        print(f"\n-- 정답 경계에서 가장 가까운 침묵 한가운데까지의 거리 "
              f"(경계 {len(distances)}개, 지금 VAD 값 기준) --")
        print(f"  중앙값 {pct(50)}ms   75% {pct(75)}ms   90% {pct(90)}ms   "
              f"95% {pct(95)}ms")
        within = sum(1 for d in distances if d <= 400)
        print(f"  400ms(지금 `resplit._snap_to_silence`의 폭) 안에 드는 경계: "
              f"{100 * within / len(distances):.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
