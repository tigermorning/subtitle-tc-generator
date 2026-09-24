"""1차 번역의 **번호 밀림**을 잰다 — 대사가 이웃 자막 번호로 옮겨 앉은 자리.

## 왜 있는가

1차 번역은 자막 12개를 번호를 붙여 한 번에 보낸다. 문장 하나가 자막 두 개에
걸치면 모델이 앞 번호에 통째로 옮기고 뒤 번호들에 다음 대사를 당겨 넣는다.
번호는 다 있어서 `_parse_numbered`의 번호 검사도 빈 번호 재질문도 통과하고,
타임코드는 번호에 걸려 있으니 **대사가 말보다 먼저 뜨는 자막**이 조용히 나간다
(2026-09-24, exaone3.5 · 프로젝트 헤일 메리 영어 SDH 세 구간 431큐 중 약 21큐).

프롬프트를 고칠 때마다 같은 자리를 같은 방법으로 다시 재야 전후를 견줄 수 있다.
이 도구가 그 "같은 방법"이다.

## 어떻게 재나

    원문(영어 자막) --1차 번역--> 한국어 --역번역--> 영어
    역번역 N이 제 원문보다 이웃 원문(N±1, N±2)과 더 겹치면 밀림 의심

생성기 코드를 그대로 부른다(`translate_events` · `backtranslate.run` ·
`backtranslate.shift_suspects`). 판정 규칙은 `shift_suspects`에 있다.

## 이 방법이 못 재는 것 (결과에 같이 적는다)

- **역번역도 모델이다.** 역번역 단계에서 밀린 것도 같이 잡힌다 — 한국어 결과를
  열어 어느 단계에서 밀렸는지 사람이 본다.
- **연쇄 밀림의 가운데는 못 잡는다.** 어느 원문과도 안 겹치는 자리는 셀 수 없다.
  그래서 이 숫자는 밀림 자막 수의 **하한**이다.
- **한 번 돌린 값으로 단정하지 않는다.** 온도 0.2라도 실행마다 흔들린다.
  `--repeat`로 여러 번 돌려 범위를 본다.
- 번역문·원문이 결과 파일에 들어간다. 결과는 `.work/`(gitignored)에만 둔다.

## 쓰는 법

    python tools/translate_shift_probe.py "학습한 TC 및 자막 모음/블루레이_Project Hail Mary/영어_SDH.srt"
    python tools/translate_shift_probe.py SRC.srt --starts 400 900 1400 --count 144 --repeat 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checker import backtranslate as bt  # noqa: E402
from checker.model import Event  # noqa: E402
from checker.parsers import parse  # noqa: E402
from checker.translate import make_translator, translate_events  # noqa: E402


def probe(events: list[Event], translator, progress=None) -> dict:
    """한 구간을 번역·역번역하고 밀림 의심을 센다. 원문·번역·역번역을 함께 낸다."""
    cues = translate_events(events, translator, progress=progress)
    korean = [Event(e.index, e.start_ms, e.end_ms, c.text) for e, c in zip(events, cues)]
    back = bt.run(korean, translator, language="en", progress=progress)
    source = {e.index: e.text for e in events}
    shifted = bt.shift_suspects(korean, source, back)
    return {
        "cues": len(events),
        "first": events[0].index if events else None,
        "last": events[-1].index if events else None,
        "shifted": [s.to_dict() for s in shifted],
        "retried": sum(1 for c in cues if "다시 물었" in c.note),
        "rows": [{"index": e.index, "source": e.text, "korean": c.text, "note": c.note,
                  "back": back.get(e.index, "")} for e, c in zip(events, cues)],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("srt", type=Path, help="원어 자막(영어)")
    ap.add_argument("--starts", type=int, nargs="+", default=[400, 900, 1400],
                    help="구간 시작(빈 자막을 뺀 순번, 0부터)")
    ap.add_argument("--count", type=int, default=144, help="구간 길이(큐)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--model", default=None)
    ap.add_argument("--label", default="current", help="결과 파일 이름에 붙일 표시")
    ap.add_argument("--out", type=Path, default=ROOT / ".work" / "shift_probe")
    args = ap.parse_args(argv)

    events = [e for e in parse(args.srt) if e.text.strip()]
    translator = make_translator(args.model, prefer_cli=False)
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"모델 {translator.model} · {args.srt.name} · 구간 {args.starts} × {args.count}큐 "
          f"× {args.repeat}회", flush=True)

    totals = []
    for rep in range(1, args.repeat + 1):
        row = []
        for start in args.starts:
            part = events[start:start + args.count]
            t0 = time.time()
            result = probe(part, translator)
            result.update({"file": args.srt.name, "start": start, "repeat": rep,
                           "model": translator.model, "label": args.label,
                           "secs": round(time.time() - t0)})
            name = f"{args.label}_{start}_r{rep}.json"
            (args.out / name).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
            row.append(len(result["shifted"]))
            print(f"  {rep}회 구간 {start}: 밀림 의심 {len(result['shifted'])} / "
                  f"{result['cues']}큐 · 재질문 {result['retried']} · {result['secs']}초 "
                  f"-> {name}", flush=True)
        totals.append(sum(row))
    print(f"합계(회차별) {totals} — 밀림 자막 수의 하한이다(연쇄 가운데는 못 셈)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
