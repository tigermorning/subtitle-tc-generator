"""정독 기록을 세어 **안 본 범위**를 보여 준다(규칙 12).

## 왜 필요한가

규칙 12는 "한 회차가 다룬 범위와 안 다룬 범위를 분명히 남긴다", "'다 됐습니다'라고
보고하기 전에 정말 전부 봤는지 스스로 확인한다"고 정한다. 그런데 그 기록이 산문
(`이미지-판정.md`·`이미지-정독.md`)에만 있어서 **몇 개 중 몇 개를 봤는지 셀 수가
없었다.** 그래서 `이미지-정독.md`는 머리말에 "127장 전수 정독"이라고 적혀 있는데,
실제로 개별 기록이 있는 것은 그보다 적다.

`rules/private/sources/작업자-자료/정독-기록.yaml`이 그 셈을 할 수 있는 형식이고, 이
도구가 센다.

## 무엇을 세나

    반영함 · 정독함 · 그룹판정 · 안읽음 · 보류    기록에 있는 상태
    미확인                                      `total`에서 위를 뺀 나머지

**미확인은 "안 봤다"가 아니라 "봤다는 기록이 없다"다**(규칙 3 — 모르는 것은 모른다고
남긴다). 산문 어딘가에서 봤을 수도 있지만, 세는 자리에서는 기록이 없으면 없는 것이다.

## 막지 않는다

기본은 보고서다(종료 코드 0). `--strict`를 주면 미확인이 하나라도 있을 때 1로
끝난다 — "다 봤다"고 주장하는 자리(문서·커밋 메시지)에서 스스로 확인할 때 쓴다.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "rules" / "private" / "sources" / "작업자-자료" / "정독-기록.yaml"

STATES = ("반영함", "정독함", "그룹판정", "안읽음", "보류")
_ID = re.compile(r"^([A-Za-z]+)-?(\d+)$")


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def load(path: Path | None = None) -> dict:
    import yaml
    path = LEDGER if path is None else path
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def tally(source: dict) -> dict:
    """한 자료의 상태별 개수와 문제 목록.

    `ids`를 적은 자료는 id로 세고, `count`만 적은 자료는 수로 센다. 둘을 섞어
    적어도 된다 — 나중에 id를 매기게 되면 그때부터 id로 옮겨 적으면 그만이다.
    """
    counts: dict[str, int] = {}
    seen: set[str] = set()
    problems: list[str] = []
    total = int(source.get("total") or 0)

    for record in source.get("records") or []:
        state = record.get("state")
        if state not in STATES:
            problems.append(f"모르는 상태: {state} (쓸 수 있는 것: {', '.join(STATES)})")
            continue
        ids = record.get("ids") or []
        for one in ids:
            if one in seen:
                problems.append(f"같은 것이 두 번 적혔다: {one}")
            seen.add(one)
        counts[state] = counts.get(state, 0) + len(ids) + int(record.get("count") or 0)

    counted = sum(counts.values())
    if counted > total:
        problems.append(f"적힌 수({counted})가 전체({total})보다 많다")
    return {"total": total, "counts": counts, "ids": seen,
            "unknown": max(0, total - counted), "problems": problems}


def missing_ids(source: dict, result: dict) -> list[str]:
    """id를 매긴 자료에서 기록에 없는 id를 뽑는다. 못 뽑으면 빈 목록."""
    if not result["ids"] or result["unknown"] <= 0:
        return []
    prefixes = {m.group(1) for m in (_ID.match(i) for i in result["ids"]) if m}
    if len(prefixes) != 1:
        return []
    prefix = prefixes.pop()
    width = len(next(iter(result["ids"])).split("-")[-1])
    everything = {f"{prefix}-{i:0{width}d}" for i in range(1, result["total"] + 1)}
    return sorted(everything - result["ids"])


def report(data: dict) -> tuple[str, int]:
    """`(사람이 읽는 보고서, 미확인 총합)`."""
    lines: list[str] = []
    unknown_total = 0
    for source in data.get("sources") or []:
        result = tally(source)
        unknown_total += result["unknown"]
        state_text = " · ".join(f"{k} {v}" for k, v in result["counts"].items()) or "기록 없음"
        lines.append(f"{source.get('file')}  ({result['total']}개)")
        lines.append(f"  {state_text}"
                     + (f" · **미확인 {result['unknown']}**" if result["unknown"] else ""))
        gaps = missing_ids(source, result)
        if gaps:
            shown = " ".join(gaps[:12]) + (f" 외 {len(gaps) - 12}개" if len(gaps) > 12 else "")
            lines.append(f"  미확인: {shown}")
        for problem in result["problems"]:
            lines.append(f"  [문제] {problem}")
    return "\n".join(lines), unknown_total


def main() -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--strict", action="store_true",
                    help="미확인이 하나라도 있으면 1로 끝난다")
    a = ap.parse_args()

    path = a.ledger or LEDGER
    if not path.is_file():
        print(f"정독 기록을 찾지 못했습니다: {path}", file=sys.stderr)
        return 2
    text, unknown = report(load(path))
    print(text)
    if unknown:
        print(f"\n미확인 합계 {unknown}개 — 봤다는 기록이 없는 것이다"
              f"(안 봤다는 뜻은 아니다). 확인하면 정독-기록.yaml에 상태를 적는다.")
    else:
        print("\n미확인 없음 — 모든 자료에 상태가 적혀 있다.")
    return 1 if (a.strict and unknown) else 0


if __name__ == "__main__":
    raise SystemExit(main())
