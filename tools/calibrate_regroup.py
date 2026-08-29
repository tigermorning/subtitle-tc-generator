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

**정답 언어가 발화 언어와 같은 kind만 다룬다**(예: 한국어 SDH 정답 vs 한국어
발화). 번역 kind(예: 영어 번역 정답)는 번역 전 원시 전사를 직접 비교하는 게
무의미해서 건너뛴다 — 번역까지 거친 결과로 비교하려면 이 가벼운 스윕이 아니라
`checker --generate --translate`+`--against`를 따로 돌려야 한다.
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
    """(작품, 회차, kind) 조합마다 하나씩 — 한 회차에 kind(sdh/translation)가
    여럿이면 같은 raw whisper 세그먼트(같은 영상, 같은 source_lang)를 서로
    다른 정답과 각각 대조한다(schema_version 2, 2026-08-30)."""
    out = []
    for work_name, work in (data.get("works") or {}).items():
        genre = work.get("genre")
        if only_genre and genre != only_genre:
            continue
        source_lang = work.get("source_lang")
        for ep_name, ep in (work.get("episodes") or {}).items():
            video = ROOT / ep["video"] if ep.get("video") else None
            if not (video and video.is_file() and source_lang):
                continue
            for kind_name, kind_entry in (ep.get("kinds") or {}).items():
                truth = ROOT / kind_entry["truth"] if kind_entry.get("truth") else None
                if not (truth and truth.is_file()):
                    continue
                if kind_entry.get("lang") != source_lang:
                    # 이 스윕은 **번역 전** 원시 전사(항상 source_lang)를 정답과
                    # 직접 비교한다. 정답이 다른 언어(예: translation kind의
                    # 영어)면 글자가 애초에 안 맞아서 유사도 자체가 무의미하다
                    # (2026-08-30 실측: 예능A 15회 translation에서 "genuine"
                    # 3개가 나왔는데 전부 우연히 영어로 말한 코드스위칭 구간이었다
                    # — 번역 품질과 무관한 잡음). 번역 kind를 실제로 검증하려면
                    # 번역 단계까지 돌려야 하는데 그건 이 가벼운 스윕의 목적을
                    # 벗어난다(비용이 크다) — 그래서 여기선 건너뛴다.
                    print(f"[건너뜀] {work_name} {ep_name}회 [{kind_name}]: "
                          f"정답 언어({kind_entry.get('lang')})가 발화 언어"
                          f"({source_lang})와 달라 원시 전사와 직접 비교 못 함")
                    continue
                out.append({"work": work_name, "episode": ep_name, "kind": kind_name,
                            "genre": genre, "video": video, "truth": truth,
                            "source_lang": source_lang})
    return out


def raw_segments(target: dict) -> list[Event]:
    # 캐시는 (작품, 회차) 단위다 — kind가 달라도 같은 영상·같은 발화 언어라
    # whisper 전사 결과는 같다(regroup은 kind별 truth와만 비교, 전사는 공유).
    cache = CACHE_ROOT / target["work"] / f"{target['episode']}.srt"
    segments = transcribe(target["video"], language=target["source_lang"], use_gpu=True,
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
        print(f"=== {t['work']} {t['episode']}회 [{t['kind']}] (장르: {t['genre']}) ===")
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
