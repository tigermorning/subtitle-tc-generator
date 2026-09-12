"""TC를 **짝짓기 없이** 잰다 — 경계집합 precision/recall/F1.

## 왜 새 자가 필요한가

지금까지 쓰던 자(`--against`의 `pairs` + 진짜 짝 필터)는 텍스트 유사도로 자막을
짝지은 뒤 그 짝의 시간 차이를 본다. 두 가지를 구조적으로 못 본다.

1. **분할 단위가 다르면 짝이 안 지어진다.** 우리 자막 하나가 정답 둘을 덮으면
   그 자리는 통째로 통계에서 빠진다 — 남은 오차의 본체로 지목된 바로 그 현상이
   자에서 사라진다(2026-09-11 관측: 1500ms 넘는 이상치가 전부 분할 단위 차이).
2. **허용오차 100ms가 헐겁다.** 정답 작업자 자신의 흔들림이 약 2프레임 폭이다
   (인점 사분위 -146~-59ms). 100ms 자로는 우리가 작업자 수준에 닿았는지 모른다.

이 도구는 텍스트를 아예 안 본다. **인점집합끼리, 아웃점집합끼리** 최근접 거리를
재서 허용오차별로 precision/recall/F1을 낸다. FA-Bench(정렬기 벤치마크)가 쓰는
방식과 같고, 허용오차는 프레임 단위로 잡는다.

    recall     정답 경계 중 우리 경계가 허용오차 안에 있는 비율 (놓친 자리)
    precision  우리 경계 중 정답 경계가 허용오차 안에 있는 비율 (없는 자리에 찍은 것)
    F1         둘의 조화평균

**짝이 1:1이 아니어도 된다** — 한쪽에 여럿이 몰리면 precision이 떨어져 그 사실이
드러난다. 그게 이 자의 요점이다.

## 한계

- SDH 정답지에는 효과음·음악 자막이 섞여 있다. 기본값은 대괄호·소괄호·음표만으로
  이루어진 자막을 **양쪽에서** 뺀다(`--with-sfx`로 끄면 다 센다).
- 경계가 많을수록 우연히 가까워진다. 그래서 **자막 개수비**를 함께 낸다 — 개수가
  크게 다르면 F1만 보고 판단하지 않는다.
- 원어가 한국어가 아닌 작품에서는 번역 자막 경계가 원어 발화와 조금 어긋난다.

## 쓰는 법

    python tools/tc_boundary_f1.py <우리.srt> <정답.srt> [--fps 23.976] [--with-sfx]
    python tools/tc_boundary_f1.py --pairs <우리1.srt>=<정답1.srt> <우리2.srt>=<정답2.srt>
"""
from __future__ import annotations

import argparse
import bisect
import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checker.parsers import parse

SFX = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪?)\s*$")
DEFAULT_FPS = 23.976


def is_sfx(event) -> bool:
    lines = [line for line in event.text.split("\n") if line.strip()]
    return bool(lines) and all(SFX.match(line) for line in lines)


def boundaries(events, with_sfx: bool) -> tuple[list[int], list[int]]:
    kept = [e for e in events if with_sfx or not is_sfx(e)]
    return (sorted(e.start_ms for e in kept), sorted(e.end_ms for e in kept))


def nearest(sorted_values: list[int], x: int) -> int | None:
    if not sorted_values:
        return None
    i = bisect.bisect_left(sorted_values, x)
    candidates = [sorted_values[j] for j in (i - 1, i) if 0 <= j < len(sorted_values)]
    return min(abs(v - x) for v in candidates)


def hit_rate(source: list[int], target: list[int], tolerance_ms: int) -> float:
    """`source`의 경계 중 `target`에 허용오차 안으로 닿는 비율."""
    if not source:
        return 0.0
    hits = sum(1 for x in source if (nearest(target, x) or 10 ** 9) <= tolerance_ms)
    return hits / len(source)


def distances(source: list[int], target: list[int]) -> list[int]:
    return [d for d in (nearest(target, x) for x in source) if d is not None]


def report(name: str, ours, truth, fps: float, with_sfx: bool) -> dict:
    our_in, our_out = boundaries(ours, with_sfx)
    truth_in, truth_out = boundaries(truth, with_sfx)
    frame_ms = 1000.0 / fps
    tolerances = [("1프레임", round(frame_ms)), ("2프레임", round(frame_ms * 2)),
                  ("100ms", 100), ("200ms", 200)]

    print(f"\n== {name}")
    print(f"   자막 개수: 우리 {len(our_in)} / 정답 {len(truth_in)} "
          f"= {len(our_in) / len(truth_in):.2f}배" if truth_in else "   정답 없음")
    rows = {}
    for label, points in (("인점", (our_in, truth_in)), ("아웃점", (our_out, truth_out))):
        ours_pts, truth_pts = points
        gaps = distances(truth_pts, ours_pts)
        median = st.median(gaps) if gaps else float("nan")
        print(f"   {label} — 정답 경계에서 가장 가까운 우리 경계까지 |중앙| {median:.0f}ms")
        print(f"   {'허용':>8} {'recall':>8} {'precision':>10} {'F1':>7}")
        for tol_name, tol in tolerances:
            recall = hit_rate(truth_pts, ours_pts, tol)
            precision = hit_rate(ours_pts, truth_pts, tol)
            f1 = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
            rows[(label, tol_name)] = (recall, precision, f1)
            print(f"   {tol_name:>8} {recall:>7.1%} {precision:>9.1%} {f1:>6.1%}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ours", type=Path, nargs="?")
    ap.add_argument("truth", type=Path, nargs="?")
    ap.add_argument("--pairs", nargs="*", default=None,
                    help="<우리.srt>=<정답.srt> 꼴로 여러 회차를 한 번에")
    ap.add_argument("--fps", type=float, default=DEFAULT_FPS)
    ap.add_argument("--with-sfx", action="store_true",
                    help="효과음·음악 자막도 경계로 센다(기본은 양쪽에서 뺀다)")
    a = ap.parse_args()

    jobs = []
    if a.pairs:
        for item in a.pairs:
            ours, truth = item.split("=", 1)
            jobs.append((Path(ours), Path(truth)))
    elif a.ours and a.truth:
        jobs.append((a.ours, a.truth))
    else:
        ap.error("<우리.srt> <정답.srt> 또는 --pairs가 필요합니다")

    for ours_path, truth_path in jobs:
        report(ours_path.name, parse(ours_path), parse(truth_path), a.fps, a.with_sfx)
    print("\n개수비가 1에서 멀면 F1만 보고 판단하지 않는다 — 경계가 많으면 우연히 가까워진다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
