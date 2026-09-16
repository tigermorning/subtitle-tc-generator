"""정답지에 규정 검사기를 돌려 **검사기 자신**을 검증한다.

## 왜 필요한가

정답지(`학습한 TC 및 자막 모음/`)는 사람이 만들어 발주처가 받아 준 납품물이다.
거기에 우리 검사기(`check_events`)를 돌렸을 때 위반이 쏟아지면, 틀린 쪽은 정답지보다
**검사기나 프로파일일 가능성이 먼저**다. 채점기를 모범 답안으로 먼저 검증하는 것과
같은 원리다 — 모범 답안이 떨어지는 채점기로 우리 초안을 채점하면 그 점수를 믿을 수 없다.

지금까지는 이 확인을 한 번씩 손으로만 했다(C3x 2,622개, `korean_break` 1,926개).
다시 돌릴 수 있는 자리가 없어서, 규칙을 고친 뒤 오탐이 되살아나도 아무도 모른다.

## 무엇을 내나

위반을 규칙(`rule_id`)별로 모아 작품·회차별 건수와 비율, 예시를 낸다. 그리고 규칙마다
**분류 후보**를 붙인다.

    검사기·프로파일 의심   둘 이상의 작품에서 걸렸다
    한 작품 관행 의심      한 작품의 모든 회차(2회차 이상)에서 `--repeat`건 이상씩 걸렸다
                          (규칙 11 — 한 작품에서만 나온 것은 그 작품의 습관일 수 있다)
    사람 실수 후보         그 밖 — 일부 회차에만, 드물게 걸렸다

비율이 아니라 **퍼짐**으로 가른다. 사람 실수는 회차를 넘어 반복되지 않는다.
**후보이지 판정이 아니다**(규칙 3·4). 분류는 사람이 볼 순서를 정하는 도구일 뿐이다.
어느 쪽인지는 예시를 열어 사람이 정하고, 규정을 고치는 것은 문건 근거로만 한다(규칙 5·11).
"검사기·프로파일 의심"은 두 작품이 **같은 프로파일**일 때만 뜻이 있다 — 리포트의
작품 표기에 프로파일을 함께 적는 이유다.

## 무엇을 안 하나

- 한국어 교정기(사전·어문 규범)는 돌리지 않는다. 규정 검사기만 잰다 — 층이 다르다.
- 정답지를 고치지 않는다(규칙 13). 읽기만 한다.
- 프레임 단위 규정은 `--fps`로 환산한다. 영상이 없으므로 **fps는 가정값**이고
  리포트 머리에 그 값을 적는다.
- 작품 연도와 자료 기준 시점 비교(규칙 11)는 원장에 연도가 없어 아직 못 한다.

## 쓰는 법

    python tools/truth_self_check.py                        # 원장의 정답지 전부
    python tools/truth_self_check.py --work <원장 작품 키>   # 작품 하나
    python tools/truth_self_check.py --file 정답.srt --profile netflix/ko-sdh [--genre variety]
    python tools/truth_self_check.py --json 결과.json

막지 않는다(종료 코드 0). 정답지가 하나도 안 읽히면 2로 끝난다 — 조용히 "위반 0건"으로
보이면 안 된다.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from checker import ProfileError, check_events, load_profile  # noqa: E402
from checker import genre as _genre  # noqa: E402
from checker.parsers import parse  # noqa: E402

LEDGER = ROOT / "rules" / "private" / "corpus" / "corpus_status.yaml"
DEFAULT_FPS = 23.976
DEFAULT_REPEAT = 3        # 회차마다 이만큼 이상 걸려야 '반복'으로 본다
EXAMPLES = 3

SYSTEMIC = "검사기·프로파일 의심"
ONE_WORK = "한 작품 관행 의심"
SCATTERED = "사람 실수 후보"


@dataclass
class Target:
    """검사할 정답지 하나."""

    work: str
    episode: str
    platform: str
    language: str
    kind: str                       # sdh / translation
    genre: str | None
    path: Path


@dataclass
class Result:
    target: Target
    cues: int = 0
    violations: list[dict] = field(default_factory=list)
    unimplemented: list[str] = field(default_factory=list)
    skipped: list = field(default_factory=list)
    error: str = ""
    events: list = field(default_factory=list, repr=False)


def _ms(ms: int) -> str:
    h, rest = divmod(int(ms), 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def targets_from_ledger(ledger: dict, root: Path = ROOT, work: str | None = None
                        ) -> tuple[list[Target], list[str]]:
    """원장에서 정답지 목록을 뽑는다. 못 쓰는 항목은 이유와 함께 따로 돌려준다.

    kind 키가 `translation_fr`처럼 언어를 달고 있어도 앞부분(`translation`)이 종류다.
    """
    found: list[Target] = []
    skipped: list[str] = []
    for name, w in (ledger.get("works") or {}).items():
        if work and name != work:
            continue
        for ep, e in (w.get("episodes") or {}).items():
            for key, k in ((e or {}).get("kinds") or {}).items():
                label = f"{name} E{ep} {key}"
                kind = str(key).split("_", 1)[0]
                truth = (k or {}).get("truth")
                lang = (k or {}).get("lang")
                if kind not in ("sdh", "translation"):
                    skipped.append(f"{label}: 종류를 알 수 없음({key})")
                    continue
                if not truth:
                    skipped.append(f"{label}: 원장에 정답지 경로가 없음")
                    continue
                path = root / str(truth)
                if not path.is_file():
                    skipped.append(f"{label}: 정답지 파일이 없음({truth})")
                    continue
                if not lang or "/" in str(lang):
                    skipped.append(f"{label}: 언어가 하나로 정해지지 않음({lang})")
                    continue
                found.append(Target(name, str(ep), str(w.get("platform")), str(lang),
                                    kind, w.get("genre"), path))
    return found, skipped


def run_one(target: Target, fps: float) -> Result:
    """정답지 하나를 규정 프로파일로 검사한다. 프로파일이 없으면 오류로 남긴다."""
    res = Result(target)
    try:
        profile = load_profile(target.platform, target.language, target.kind)
        if target.genre:
            profile = _genre.apply(profile, target.genre)
    except (ProfileError, FileNotFoundError, KeyError) as exc:
        res.error = f"프로파일 없음: {exc}"
        return res
    events = parse(target.path)
    res.cues = len(events)
    res.events = events
    if not events:
        res.error = "자막을 읽지 못함"
        return res
    report = check_events([{"index": e.index, "start_ms": e.start_ms, "end_ms": e.end_ms,
                            "text": e.text, "kind": e.kind} for e in events],
                          profile, fps=fps)
    res.violations = report["violations"]
    res.unimplemented = report.get("unimplemented_checks") or []
    res.skipped = report.get("skipped_checks") or []
    return res


def work_key(t: Target) -> str:
    """작품 단위. 같은 작품의 SDH와 번역은 프로파일이 다르므로 따로 센다."""
    return f"{t.work} [{t.platform}/{t.language}-{t.kind}]"


def episode_key(t: Target) -> str:
    return f"{t.work} E{t.episode} {t.kind}"


def classify(by_work: dict[str, int], by_episode: dict[str, int],
             episodes_by_work: dict[str, list[str]], repeat: int = DEFAULT_REPEAT) -> str:
    """걸린 **자리의 퍼짐**으로 후보를 정한다. 비율로 가르지 않는다.

    비율 문턱은 흔한 짧은 자막이 많은 작품에서 반복 관행을 '드문 실수'로 떨어뜨렸다
    (예능A G01: 두 회차 모두 걸렸는데 2.2%). 사람 실수는 반복되지 않는다는 쪽이
    더 믿을 만한 기준이다.
    """
    works = {wk.split(" [", 1)[0] for wk in by_work}
    if len(works) >= 2:
        return SYSTEMIC
    for wk in by_work:
        eps = episodes_by_work.get(wk) or []
        if len(eps) >= 2 and all(by_episode.get(ep, 0) >= repeat for ep in eps):
            return ONE_WORK
    return SCATTERED


def summarize(results: list[Result], repeat: int = DEFAULT_REPEAT) -> list[dict]:
    """규칙별로 모아 분류 후보를 붙인다. 의심이 큰 분류부터, 그 안에서는 비율 순."""
    cues_by_work: dict[str, int] = defaultdict(int)
    episodes_by_work: dict[str, list[str]] = defaultdict(list)
    for r in results:
        if not r.error:
            cues_by_work[work_key(r.target)] += r.cues
            episodes_by_work[work_key(r.target)].append(episode_key(r.target))

    rules: dict[str, dict] = {}
    for r in results:
        if r.error:
            continue
        wk = work_key(r.target)
        for v in r.violations:
            rule = rules.setdefault(v["rule_id"], {
                "rule_id": v["rule_id"], "clause": v.get("clause", ""),
                "hits": 0, "by_work": defaultdict(int), "by_episode": defaultdict(int),
                "examples": []})
            rule["hits"] += 1
            rule["by_work"][wk] += 1
            rule["by_episode"][episode_key(r.target)] += 1
            idx = v.get("event_index", 0)
            where = f"{episode_key(r.target)} #{idx}"
            # 한 자막이 같은 규칙에 여러 번 걸리면(줄마다) 예시가 같은 자리로 채워진다.
            if len(rule["examples"]) < EXAMPLES and \
                    all(ex["where"] != where for ex in rule["examples"]):
                ev = next((e for e in r.events if e.index == idx), None) \
                    if not v.get("text") else None
                rule["examples"].append({
                    "where": where,
                    "tc": _ms(ev.start_ms) if ev else "",
                    "text": (v.get("text") or (ev.text if ev else "")).replace("\n", " / "),
                    "message": v.get("message", "")})

    out = []
    for rule in rules.values():
        rates = {wk: 100 * n / cues_by_work[wk] for wk, n in rule["by_work"].items()
                 if cues_by_work.get(wk)}
        label = classify(rule["by_work"], rule["by_episode"], episodes_by_work, repeat)
        out.append({
            "rule_id": rule["rule_id"], "clause": rule["clause"], "hits": rule["hits"],
            "label": label, "max_pct": round(max(rates.values()), 2) if rates else 0.0,
            "by_work": {wk: {"hits": n, "pct": round(rates.get(wk, 0.0), 2)}
                        for wk, n in sorted(rule["by_work"].items())},
            "by_episode": dict(sorted(rule["by_episode"].items())),
            "examples": rule["examples"]})
    order = {SYSTEMIC: 0, ONE_WORK: 1, SCATTERED: 2}
    out.sort(key=lambda x: (order[x["label"]], -x["max_pct"], x["rule_id"]))
    return out


def render(results: list[Result], summary: list[dict], skipped: list[str], fps: float,
           repeat: int) -> str:
    lines = [f"# 정답지 자기검증 — fps {fps:g}(가정값), 반복 기준 회차당 {repeat}건",
             "분류는 후보다. 예시를 열어 사람이 정한다(규칙 3·4).", ""]
    ok = [r for r in results if not r.error]
    lines.append(f"## 읽은 정답지 {len(ok)}개 / 못 읽음 {len(results) - len(ok) + len(skipped)}개")
    for r in results:
        t = r.target
        head = f"- {t.work} E{t.episode} {t.platform}/{t.language}-{t.kind}"
        head += f" (장르 {t.genre})" if t.genre else ""
        if r.error:
            lines.append(f"{head}: **{r.error}**")
        else:
            pct = 100 * len(r.violations) / r.cues if r.cues else 0
            lines.append(f"{head}: 자막 {r.cues}개, 위반 {len(r.violations)}건 ({pct:.1f}%)")
    for s in skipped:
        lines.append(f"- 건너뜀: {s}")

    unimpl = sorted({u for r in ok for u in r.unimplemented})
    if unimpl:
        lines += ["", f"미구현 검사(이 결과에 안 잡힘): {', '.join(unimpl)}"]
    skipped_checks = sorted({str(s) for r in ok for s in r.skipped})
    if skipped_checks:
        lines += [f"자료가 없어 못 돈 검사: {'; '.join(skipped_checks)}"]

    if not ok:
        return "\n".join(lines)     # 하나도 못 읽었는데 "위반 없음"이라고 쓰지 않는다
    lines += ["", "## 규칙별"]
    if not summary:
        lines.append("위반 없음.")
    for rule in summary:
        lines.append(f"\n### {rule['rule_id']} — {rule['label']} "
                     f"(총 {rule['hits']}건, 최대 {rule['max_pct']:.1f}%)")
        if rule["clause"]:
            lines.append(f"조항: {rule['clause']}")
        for wk, v in rule["by_work"].items():
            lines.append(f"- {wk}: {v['hits']}건 ({v['pct']:.1f}%)")
        for ex in rule["examples"]:
            tc = f" {ex['tc']}" if ex["tc"] else ""
            lines.append(f"  - 예) {ex['where']}{tc} 「{ex['text'][:60]}」 {ex['message'][:80]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--work", help="원장의 작품 키 하나만")
    ap.add_argument("--file", type=Path, help="원장 밖 정답지 하나")
    ap.add_argument("--profile", help="--file과 함께: 플랫폼/언어-종류 (예: netflix/ko-sdh)")
    ap.add_argument("--genre", choices=["documentary", "drama", "variety"])
    ap.add_argument("--fps", type=float, default=DEFAULT_FPS)
    ap.add_argument("--repeat", type=int, default=DEFAULT_REPEAT,
                    help="회차마다 이 건수 이상이면 반복(관행)으로 본다")
    ap.add_argument("--json", type=Path, help="결과를 JSON으로도 남긴다")
    args = ap.parse_args(argv)

    skipped: list[str] = []
    if args.file:
        if not args.profile or "/" not in args.profile or "-" not in args.profile:
            print("--file에는 --profile 플랫폼/언어-종류가 필요합니다", file=sys.stderr)
            return 2
        platform, rest = args.profile.split("/", 1)
        language, kind = rest.split("-", 1)
        targets = [Target(args.file.stem, "-", platform, language, kind, args.genre, args.file)]
    else:
        import yaml
        if not args.ledger.is_file():
            print(f"원장이 없습니다: {args.ledger}", file=sys.stderr)
            return 2
        ledger = yaml.safe_load(args.ledger.read_text(encoding="utf-8")) or {}
        targets, skipped = targets_from_ledger(ledger, work=args.work)

    results = [run_one(t, args.fps) for t in targets]
    if not any(not r.error for r in results):
        print(render(results, [], skipped, args.fps, args.repeat))
        print("\n정답지를 하나도 검사하지 못했습니다.", file=sys.stderr)
        return 2
    summary = summarize(results, args.repeat)
    print(render(results, summary, skipped, args.fps, args.repeat))
    if args.json:
        args.json.write_text(json.dumps({
            "fps": args.fps, "repeat": args.repeat, "skipped": skipped,
            "targets": [{"work": r.target.work, "episode": r.target.episode,
                         "profile": f"{r.target.platform}/{r.target.language}-{r.target.kind}",
                         "genre": r.target.genre, "cues": r.cues,
                         "violations": len(r.violations), "error": r.error}
                        for r in results],
            "rules": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
