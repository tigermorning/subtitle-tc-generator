"""이미 확정된 정답지에서 `chars_per_cue`를 뒤늦게 재 넣는다(T14 뒷정리).

## 왜 필요한가

`resplit.py`가 학습값을 소비하는 경로는 2026-09-01에 붙었다(T14). 그런데
**그 값이 들어 있는 파일이 `rules/learned/disney/ko-sdh.yaml` 하나뿐**이라,
나머지 발주처·언어 조합에서는 경로가 있어도 아무 일도 하지 않는다. 나머지
학습값은 `chars_per_cue`가 생기기 전에 뽑혔기 때문이다.

영상은 대부분 지웠지만(규칙 13) **정답지 `.srt`는 남아 있다**
(`학습한 TC 및 자막 모음/`). 통계만 다시 재는 데는 영상이 필요 없다.

## 무엇을 하고, 무엇을 안 하나

**쓰지 않는다. 재고 견주기만 한다.** 사람이 출력을 보고 yaml에 손으로 넣는다
(규칙 11 — 학습값이 규정을 건드리지 않게 하는 것과 같은 이유로, 기계가 파일을
직접 고치지 않는다. 디즈니 값도 이 방식으로 들어갔다).

**같은 자료인지 먼저 증명한다.** 기존 항목(duration_ms·chars_per_line·cps·
lines·gap_ms)을 다시 재서 yaml에 적힌 값과 맞는지 보여 준다. 안 맞으면 그
파일은 **건드리지 않는다** — 다른 자료를 섞으면 그 파일의 출처가 무의미해진다.

## 쓰는 법

    python tools/learned_chars_per_cue.py -p netflix -l ko -k sdh \
        "학습한 TC 및 자막 모음/넷플릭스_드라마A/E01_한국어_SDH.srt" ...

파일 목록은 **손으로 준다.** 폴더에서 자동으로 긁으면 yaml의 `from`에 적힌
작품과 다른 것이 섞여도 알아채지 못한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from checker import load_profile, ProfileError  # noqa: E402
from checker.parsers import parse  # noqa: E402
from corpus_build import stats_for  # noqa: E402

import yaml  # noqa: E402

# yaml의 `observed`는 사람이 읽기 좋게 다듬은 이름을 쓴다. `stats_for()`가 내는
# 이름과 짝을 지어야 견줄 수 있다.
_ALIAS = {"5%": ["p5", "5%"], "95%": ["p95", "95%"], "중앙값": ["중앙값"],
          "최소": ["최소"], "최대": ["최대"],
          "한 줄": ["한_줄"], "두 줄": ["두_줄"], "세 줄 이상": ["세_줄_이상"]}


def _yaml_value(block: dict, key: str):
    """yaml 쪽에서 같은 뜻의 칸을 찾는다. `범위: [최소, 최대]`도 편다."""
    for name in _ALIAS.get(key, [key]):
        if name in block:
            return block[name]
    if key in ("최소", "최대") and isinstance(block.get("범위"), list):
        span = block["범위"]
        return span[0] if key == "최소" else span[-1]
    return None


def compare(measured: dict, recorded: dict) -> list[tuple[str, object, object, bool]]:
    """`(항목, 다시 잰 값, 적힌 값, 같은가)` 목록. 적혀 있지 않은 칸은 건너뛴다."""
    rows = []
    for group, values in measured.items():
        if not isinstance(values, dict):
            continue
        block = recorded.get(group)
        if not isinstance(block, dict):
            continue
        for key, got in values.items():
            want = _yaml_value(block, key)
            if want is None:
                continue
            same = abs(float(got) - float(want)) < 0.05 if isinstance(
                got, (int, float)) and isinstance(want, (int, float)) else got == want
            rows.append((f"{group}.{key}", got, want, same))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-p", "--platform", required=True)
    ap.add_argument("-l", "--lang", required=True)
    ap.add_argument("-k", "--kind", required=True, choices=["sdh", "translation"])
    ap.add_argument("files", nargs="+", type=Path, help="정답지 .srt 파일들")
    a = ap.parse_args()

    # **글자 수 가중치는 프로파일에서 온다**(한국어 CJK 1자·그 외 0.5자).
    # 프로파일이 없는 발주처는 `resplit.py`가 애초에 그 값을 못 쓰므로 여기서도
    # 재지 않는다 — 가중치 없이 잰 값을 가중치로 세는 알고리즘에 먹이면 단위가
    # 어긋난다(규칙 2와 같은 결: 남의 기준을 빌려 쓰지 않는다).
    try:
        profile = load_profile(a.platform, a.lang, a.kind)
    except ProfileError as exc:
        print(f"프로파일이 없습니다: {exc}", file=sys.stderr)
        print("  이 조합은 resplit.py도 학습값을 못 씁니다 — 재지 않습니다.",
              file=sys.stderr)
        return 2
    weights = (profile.get("limits") or {}).get("char_weights")

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

    measured = stats_for(events, a.lang, weights)
    learned = ROOT / "rules" / "learned" / a.platform / f"{a.lang}-{a.kind}.yaml"
    recorded = {}
    if learned.is_file():
        data = yaml.safe_load(learned.read_text(encoding="utf-8")) or {}
        recorded = data.get("observed") or {}

    print(f"\n== {a.platform}/{a.lang}-{a.kind} — 자막 {len(events)}개, "
          f"파일 {len(a.files)}개")
    rows = compare(measured, recorded)
    bad = [r for r in rows if not r[3]]
    for name, got, want, same in rows:
        print(f"  {'○' if same else '✗'} {name:28} 다시 잼 {got!s:>10}   적힌 값 {want}")
    if not rows:
        print("  (견줄 기존 값이 없습니다 — 새 파일이거나 항목 이름이 다릅니다)")

    cue = measured.get("chars_per_cue") or {}
    print("\n-- 넣을 값(chars_per_cue) --")
    print(f"  중앙값: {cue.get('중앙값')}\n  p95: {cue.get('95%')}\n  최대: {cue.get('최대')}")

    if bad:
        print(f"\n**{len(bad)}개 항목이 안 맞습니다 — 이 파일은 건드리지 마세요.**")
        print("  같은 자료가 아니라는 뜻입니다(회차 빠짐·다른 트랙 등).")
        return 1
    print("\n기존 값이 전부 맞습니다 — 같은 자료입니다. 위 값을 손으로 넣으세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
