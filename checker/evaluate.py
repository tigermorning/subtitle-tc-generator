"""우리가 만든 자막을 정답과 대조한다.

**감으로 고치지 않기 위해 있다.** "타임코드가 이상하다"는 말만으로는 무엇을 얼마나
바꿔야 하는지 알 수 없다. 어느 방향으로 몇 밀리초 어긋나는지, 그것이 전 구간에서
일정한지 들쭉날쭉한지를 재야 고칠 값이 나온다.

    체계적 편차   전부 100ms 늦다        -> 상수를 고친다(고칠 수 있다)
    들쭉날쭉      어떤 건 +300 어떤 건 -200 -> 방법이 틀렸다(상수로 못 고친다)

**두 파일로 모델을 학습시킬 수는 없다.** 하지만 편차를 재고 규칙으로 굳힐 수는
있고, 정답 파일이 쌓이면 그때 학습 자료가 된다. 그래서 결과를 JSON으로도 남긴다.

자막을 짝짓는 방법: 시간이 겹치는 것 중 글자가 가장 비슷한 것. 둘 다 보는 이유는
한쪽만으로는 갈라지기 때문이다 — 시간만 보면 통합·분할된 자막이 엉뚱하게 붙고,
글자만 보면 같은 대사가 두 번 나올 때 먼 곳에 붙는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from .align import similarity
from .model import Event
from .text import count_chars


@dataclass
class Pair:
    ours: Event | None
    truth: Event | None
    score: float = 0.0

    @property
    def start_diff(self) -> int | None:
        """우리 인점 - 정답 인점. 양수면 **늦게** 시작한 것이다."""
        if self.ours is None or self.truth is None:
            return None
        return self.ours.start_ms - self.truth.start_ms

    @property
    def end_diff(self) -> int | None:
        if self.ours is None or self.truth is None:
            return None
        return self.ours.end_ms - self.truth.end_ms


@dataclass
class Comparison:
    pairs: list[Pair] = field(default_factory=list)
    ours_count: int = 0
    truth_count: int = 0

    @property
    def matched(self) -> list[Pair]:
        return [p for p in self.pairs if p.ours and p.truth]

    @property
    def missing(self) -> list[Pair]:
        """정답에는 있는데 우리가 못 만든 자막."""
        return [p for p in self.pairs if p.truth and not p.ours]

    @property
    def extra(self) -> list[Pair]:
        """우리가 만들었는데 정답에는 없는 자막."""
        return [p for p in self.pairs if p.ours and not p.truth]


def compare(ours: list[Event], truth: list[Event],
            overlap_ms: int = 2000) -> Comparison:
    """두 자막을 짝짓는다. 정답을 기준으로 본다."""
    used: set[int] = set()
    pairs: list[Pair] = []

    for want in truth:
        best, best_score = None, 0.0
        for i, have in enumerate(ours):
            if i in used:
                continue
            # 시간이 아주 멀면 후보로 보지 않는다 — 같은 대사가 두 번 나오는 작품에서
            # 글자만 보고 먼 곳에 붙는 것을 막는다.
            if have.end_ms < want.start_ms - overlap_ms:
                continue
            if have.start_ms > want.end_ms + overlap_ms:
                break
            overlap = min(have.end_ms, want.end_ms) - max(have.start_ms, want.start_ms)
            score = similarity(have.text, want.text) + (0.3 if overlap > 0 else 0.0)
            if score > best_score:
                best, best_score = i, score
        if best is not None and best_score >= 0.3:
            used.add(best)
            pairs.append(Pair(ours[best], want, best_score))
        else:
            pairs.append(Pair(None, want))

    for i, have in enumerate(ours):
        if i not in used:
            pairs.append(Pair(have, None))

    pairs.sort(key=lambda p: (p.truth or p.ours).start_ms)
    return Comparison(pairs, len(ours), len(truth))


def _spread(values: list[int]) -> dict:
    """가운데값과 흩어진 정도. 평균을 쓰지 않는 이유는 크게 튄 몇 개에 끌려가서다."""
    if not values:
        return {}
    middle = median(values)
    deviations = sorted(abs(v - middle) for v in values)
    return {
        "count": len(values),
        "median": round(middle),
        "spread": round(deviations[len(deviations) // 2]),   # 중앙절대편차
        "worst": max(values, key=abs),
        "within_100ms": sum(1 for v in values if abs(v) <= 100),
    }


def summarize(comparison: Comparison, fps: float = 23.976) -> dict:
    """무엇이 얼마나 어긋나는지. 고칠 값을 여기서 읽는다."""
    matched = comparison.matched
    starts = [p.start_diff for p in matched if p.start_diff is not None]
    ends = [p.end_diff for p in matched if p.end_diff is not None]
    frame = 1000.0 / fps

    def durations(getter):
        return [getter(p) for p in matched]

    ours_dur = [p.ours.end_ms - p.ours.start_ms for p in matched]
    truth_dur = [p.truth.end_ms - p.truth.start_ms for p in matched]

    return {
        "counts": {
            "ours": comparison.ours_count,
            "truth": comparison.truth_count,
            "matched": len(matched),
            "missing": len(comparison.missing),
            "extra": len(comparison.extra),
        },
        "start_ms": _spread(starts),
        "end_ms": _spread(ends),
        "start_frames": round(median(starts) / frame, 1) if starts else None,
        "end_frames": round(median(ends) / frame, 1) if ends else None,
        "duration_ms": {
            "ours_median": round(median(ours_dur)) if ours_dur else None,
            "truth_median": round(median(truth_dur)) if truth_dur else None,
        },
        "chars_per_cue": {
            "ours_median": round(median([count_chars(p.ours.text) for p in matched]), 1)
            if matched else None,
            "truth_median": round(median([count_chars(p.truth.text) for p in matched]), 1)
            if matched else None,
        },
        "text_similarity_median": round(median([p.score for p in matched]), 2)
        if matched else None,
    }


def report(comparison: Comparison, fps: float = 23.976, show: int = 12) -> str:
    """사람이 읽는 대조표."""
    stats = summarize(comparison, fps)
    counts = stats["counts"]
    lines = [
        f"자막 수    우리 {counts['ours']}개 / 정답 {counts['truth']}개"
        f"  (짝지음 {counts['matched']}, 빠뜨림 {counts['missing']}, 군더더기 {counts['extra']})",
    ]

    for label, key, frames_key in (("인점", "start_ms", "start_frames"),
                                   ("아웃점", "end_ms", "end_frames")):
        data = stats[key]
        if not data:
            continue
        direction = "늦다" if data["median"] > 0 else "이르다"
        lines.append(
            f"{label}      가운데 {data['median']:+}ms ({stats[frames_key]:+}프레임) — {direction}"
            f" / 흩어짐 ±{data['spread']}ms"
            f" / 100ms 안 {data['within_100ms']}개({data['within_100ms'] * 100 // max(data['count'], 1)}%)"
            f" / 최악 {data['worst']:+}ms")

    duration = stats["duration_ms"]
    if duration["ours_median"] is not None:
        lines.append(f"표시 시간  우리 {duration['ours_median']}ms / 정답 {duration['truth_median']}ms")
    chars = stats["chars_per_cue"]
    if chars["ours_median"] is not None:
        lines.append(f"자막 길이  우리 {chars['ours_median']}자 / 정답 {chars['truth_median']}자")

    # **어긋남이 큰 것부터 보여 준다.** 평균만 보면 무엇을 고쳐야 할지 알 수 없다.
    worst = sorted((p for p in comparison.matched),
                   key=lambda p: -(abs(p.start_diff) + abs(p.end_diff)))[:show]
    if worst:
        lines.append("")
        lines.append("가장 많이 어긋난 자막")
        for p in worst:
            lines.append(
                f"  #{p.truth.index:>3} 인점 {p.start_diff:+6}ms  아웃점 {p.end_diff:+6}ms"
                f"  | {p.truth.text.replace(chr(10), ' / ')[:34]}")

    if comparison.missing:
        lines.append("")
        lines.append(f"정답에 있는데 우리가 못 만든 자막 {len(comparison.missing)}개")
        for p in comparison.missing[:show]:
            lines.append(f"  {p.truth.start_ms:>7}ms  {p.truth.text.replace(chr(10), ' / ')[:40]}")

    if comparison.extra:
        lines.append("")
        lines.append(f"우리가 만들었는데 정답에 없는 자막 {len(comparison.extra)}개")
        for p in comparison.extra[:show]:
            lines.append(f"  {p.ours.start_ms:>7}ms  {p.ours.text.replace(chr(10), ' / ')[:40]}")

    return "\n".join(lines)


def save(comparison: Comparison, path: Path, fps: float = 23.976,
         note: str = "") -> None:
    """정답 파일이 쌓이면 학습 자료가 된다. 그때 쓰려고 남긴다."""
    data = {
        "note": note,
        "fps": fps,
        "summary": summarize(comparison, fps),
        "pairs": [
            {"truth_index": p.truth.index if p.truth else None,
             "ours_index": p.ours.index if p.ours else None,
             "start_diff": p.start_diff, "end_diff": p.end_diff,
             "truth_text": p.truth.text if p.truth else None,
             "ours_text": p.ours.text if p.ours else None,
             "similarity": round(p.score, 3)}
            for p in comparison.pairs
        ],
    }
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
