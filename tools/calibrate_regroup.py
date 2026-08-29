"""`regroup.merge_cues()`의 상한값(`merge_max_ms`)을 코퍼스 전체로 실측한다.

**왜 필요한가.** 오늘(2026-08-29) 예능A 15·16회를 손으로 스윕하는 스크립트를
`.tmp/`(gitignore)에 두 번 따로 짰다 — 세션이 끝나면 사라지는 일회성 코드였다.
같은 로직을 코퍼스가 커질 때마다 다시 돌릴 수 있는 **누적 도구**로 옮긴다.

**규칙 11을 그대로 따른다.** 이 도구는 값을 자동으로 고치지 않는다 — N≥2편에서
방향이 일치하면 "이 값으로 바꿀 것을 제안합니다"까지만 내고, 실제
`rules/genre/*.yaml` 수정은 사람이 승인한 뒤 별도로 한다.

    python tools/calibrate_regroup.py                # 코퍼스 전체
    python tools/calibrate_regroup.py --genre variety # 장르 하나만

정답지(`truth`)와 원본 영상(`video`)이 **둘 다** 있는 작품/회차만 대상이다 —
`docs/corpus_status.yaml`에 이미 없는 회차는 이 도구가 스스로 찾지 않는다(정답지
학습 절차·규칙 11에 따라 사람이 원장에 먼저 등록해야 한다).
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import yaml

# Windows 콘솔 기본 인코딩(cp949)에서 한글 진행 메시지가 죽는 것을 막는다
# (규칙 10 — ffmpeg 출력과 같은 이유. 2026-08-29, 첫 실행에서 실측).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from checker.model import Event
from checker.regroup import merge_cues
from checker.evaluate import compare, genuine_pairs
from checker.parsers import parse
from checker.transcribe import transcribe
from checker import genre as genre_module

LEDGER = ROOT / "docs" / "corpus_status.yaml"
CACHE_ROOT = ROOT / "학습한 TC 및 자막 모음" / "_whisper_cache"

DURS = [800, 1200, 1600, 2000, 2500, 3000, 4000]
GAPS = [0, 100, 250, 500]


def load_ledger() -> dict:
    return yaml.safe_load(LEDGER.read_text(encoding="utf-8")) or {}


def collect_targets(data: dict, only_genre: str | None) -> list[dict]:
    out = []
    for work_name, work in (data.get("works") or {}).items():
        genre = work.get("genre")
        if only_genre and genre != only_genre:
            continue
        for ep_name, ep in (work.get("episodes") or {}).items():
            video = ROOT / ep["video"] if ep.get("video") else None
            truth = ROOT / ep["truth"] if ep.get("truth") else None
            if not (video and video.is_file() and truth and truth.is_file()):
                continue
            out.append({"work": work_name, "episode": ep_name, "genre": genre,
                        "video": video, "truth": truth})
    return out


def raw_segments(target: dict) -> list[Event]:
    cache = CACHE_ROOT / target["work"] / f"{target['episode']}.srt"
    segments = transcribe(target["video"], language="ko", use_gpu=True,
                          progress=print, cache=cache)
    return [Event(i, s.start_ms, s.end_ms, s.text) for i, s in enumerate(segments, 1)]


def sweep_one(target: dict) -> dict:
    raw = raw_segments(target)
    truth = parse(target["truth"])
    best = None
    for dur in DURS:
        for gap in GAPS:
            merged = merge_cues(raw, max_duration_ms=dur, max_gap_ms=gap, speaker_turns=None)
            comparison = compare(merged, truth)
            genuine = genuine_pairs(comparison)
            if not genuine:
                continue
            g_end_med = statistics.median([p.end_diff for p in genuine])
            score = (len(genuine), -abs(g_end_med))
            if best is None or score > best["score"]:
                best = {"dur": dur, "gap": gap, "genuine": len(genuine),
                        "g_end_med": g_end_med, "score": score}
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--genre", help="이 장르만 훑는다(예: variety)")
    args = ap.parse_args()

    data = load_ledger()
    targets = collect_targets(data, args.genre)
    if not targets:
        print("정답지+영상이 둘 다 있는 작품/회차가 없습니다 — docs/corpus_status.yaml을 먼저 채우세요.")
        return 1

    by_genre: dict[str, list] = {}
    for t in targets:
        print(f"=== {t['work']} {t['episode']}회 (장르: {t['genre']}) ===")
        result = sweep_one(t)
        if result is None:
            print("  진짜 짝을 하나도 못 찾았습니다 — 건너뜁니다.")
            continue
        print(f"  최적 dur={result['dur']}ms gap={result['gap']}ms "
              f"(genuine={result['genuine']}, g_end_med={result['g_end_med']:.0f}ms)")
        by_genre.setdefault(t["genre"] or "(장르 없음)", []).append((t, result))

    print("\n=== 장르별 종합 ===")
    for genre, results in by_genre.items():
        durs = [r["dur"] for _, r in results]
        current = None
        if genre and genre != "(장르 없음)":
            try:
                current = (genre_module.load(genre).get("timecode") or {}).get("merge_max_ms")
            except Exception:
                current = None
        print(f"\n{genre}: {len(results)}편 확인 — dur 값들 {durs}, 현재 rules/genre/{genre}.yaml = {current}")
        if len(results) < 2:
            print("  편수 부족(규칙 12: 최소 2편) — 승격 제안 안 함, 기록만 남김.")
            continue
        if len(set(durs)) == 1 and durs[0] != current:
            print(f"  ** 제안: merge_max_ms를 {durs[0]}으로 바꾸는 걸 검토하세요 "
                  f"({len(results)}편 일치, 현재 {current}) — 사람 승인 후 rules/genre/{genre}.yaml 직접 수정.**")
        elif len(set(durs)) > 1:
            print(f"  편마다 다른 값을 가리킴({durs}) — 자동 제안 안 함, 지적(규칙 3)으로 기록만.")
        else:
            print("  현재 값과 이미 일치 — 바꿀 것 없음.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
