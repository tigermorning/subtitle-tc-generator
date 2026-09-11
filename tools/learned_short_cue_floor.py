"""확정된 정답지에서 **짧은 자막의 표시 시간 바닥**을 재서 `rules/learned/`에 넣을 값을 낸다.

## 왜 필요한가

규정은 표시 시간의 하한만 정한다. 실무는 그 하한에 붙이지 않는다 — 말이 짧을수록
작업자가 아웃점을 더 늘려 **약 1초** 언저리에 자막을 세운다(2026-09-11, 드라마B
E02·E03 정답 대조: 말소리 0.6초 이하인 자막에서 정답 아웃점이 VAD 오프셋보다
+433/+424ms 뒤 — 1초 넘는 말에서는 +60~+130ms). 정답 srt만 봐도 같은 바닥이
발주처를 넘어 보인다(6자 이하 자막 표시 시간 중앙값: 넷플릭스 934~1001, 디즈니
1001~1085, 쿠팡·애플 1168, HBO 영어 정확히 1000).

`converge()`는 규정 하한까지만 늘리므로 짧은 자막이 정답보다 200~400ms 일찍
끝났다. 이 값이 그 빈자리(규칙 11 — 규정이 비워 둔 자리)를 채운다. **생성
경로에서만 쓴다** — 검사 경로는 규정 하한 그대로다.

## 무엇을 하고, 무엇을 안 하나

`tools/learned_chars_per_cue.py`와 같은 방식이다. **쓰지 않는다. 재고 견주기만
한다.** 기존 항목을 다시 재서 yaml과 맞는지(같은 자료인지) 먼저 증명하고, 맞을
때만 넣을 값을 낸다. 사람이 yaml에 손으로 넣는다.

"짧은 자막"은 **가중 글자 수 6 이하**(프로파일 `char_weights` — 한국어는 CJK 1자·
그 외 0.5자)로 잰다. 효과음·음악만 있는 자막은 뺀다 — 말이 아니라 바닥 관행이
다르다.

## 쓰는 법

    python tools/learned_short_cue_floor.py -p disney -l ko -k sdh \
        "학습한 TC 및 자막 모음/디즈니플러스_<작품>/E01_한국어_SDH.srt" ...
"""

from __future__ import annotations

import argparse
import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from checker import load_profile, ProfileError  # noqa: E402
from checker.parsers import parse  # noqa: E402
from checker.text import count_chars  # noqa: E402
from corpus_build import stats_for  # noqa: E402
from learned_chars_per_cue import compare  # noqa: E402

import yaml  # noqa: E402

SHORT_CHARS = 6.0
_SFX_LINE = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪?)\s*$")


def is_sfx_only(text: str) -> bool:
    lines = [ln for ln in text.split("\n") if ln.strip()]
    return bool(lines) and all(_SFX_LINE.match(ln) for ln in lines)


def short_cue_floor(events, weights: dict | None) -> dict:
    """말 자막 중 가중 글자 수 6 이하인 것의 표시 시간 분포."""
    speak = [e for e in events if not is_sfx_only(e.text)]
    short = sorted(e.duration_ms for e in speak
                   if count_chars(e.text, weights) <= SHORT_CHARS)
    alld = sorted(e.duration_ms for e in speak)
    out = {"기준": f"가중 글자 수 {SHORT_CHARS:g} 이하, 효과음 전용 자막 제외",
           "개수": len(short), "전체_p10": alld[len(alld) // 10] if alld else None}
    if short:
        out.update({"중앙값": int(st.median(short)), "p25": short[len(short) // 4],
                    "p75": short[3 * len(short) // 4]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-p", "--platform", required=True)
    ap.add_argument("-l", "--lang", required=True)
    ap.add_argument("-k", "--kind", required=True, choices=["sdh", "translation"])
    ap.add_argument("files", nargs="+", type=Path, help="정답지 .srt 파일들")
    a = ap.parse_args()

    try:
        profile = load_profile(a.platform, a.lang, a.kind)
        weights = (profile.get("limits") or {}).get("char_weights")
    except ProfileError:
        # 공식 프로파일이 없는 발주처(아마존·블루레이 등)도 표시 시간은 잴 수 있다 —
        # 글자 수 가중치만 없을 뿐이고, 생성 경로는 이런 발주처에도 학습값을 읽는다.
        weights = None
        print("프로파일 없음 — 글자 수를 가중치 없이 셉니다.", file=sys.stderr)

    events = []
    for path in a.files:
        if not path.is_file():
            print(f"없는 파일: {path}", file=sys.stderr)
            return 2
        got = parse(path)
        print(f"  {path.name}: {len(got)}개", file=sys.stderr)
        events += got
    if not events:
        print("자막이 없습니다.", file=sys.stderr)
        return 2

    learned = ROOT / "rules" / "learned" / a.platform / f"{a.lang}-{a.kind}.yaml"
    recorded = {}
    if learned.is_file():
        data = yaml.safe_load(learned.read_text(encoding="utf-8")) or {}
        recorded = data.get("observed") or {}

    print(f"\n== {a.platform}/{a.lang}-{a.kind} — 자막 {len(events)}개, 파일 {len(a.files)}개")
    rows = compare(stats_for(events, a.lang, weights), recorded)
    bad = [r for r in rows if not r[3]]
    for name, got, want, same in rows:
        print(f"  {'○' if same else '✗'} {name:28} 다시 잼 {got!s:>10}   적힌 값 {want}")
    if not rows:
        print("  (견줄 기존 값이 없습니다 — 새 파일이거나 항목 이름이 다릅니다)")

    floor = short_cue_floor(events, weights)
    print("\n-- 넣을 값(duration_ms.짧은자막) --")
    for k, v in floor.items():
        print(f"  {k}: {v}")

    if bad:
        print(f"\n**{len(bad)}개 항목이 안 맞습니다 — 이 파일은 건드리지 마세요.**")
        return 1
    print("\n기존 값이 전부 맞습니다 — 같은 자료입니다. 위 값을 손으로 넣으세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
