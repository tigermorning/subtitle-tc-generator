"""명령줄 진입점.

    python -m checker examples/sample.srt --platform netflix --lang ko --kind sdh
    python -m checker file.srt -p netflix -l en -k translation --json
    python -m checker --list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import check_events, available_profiles, load_profile, ProfileError
from .parsers import parse


def _format_text(report: dict, path: Path) -> str:
    out = [f"{path.name} — {report['profile']} {report['kind']}"]
    violations = report["violations"]
    if not violations:
        out.append("  위반 없음")
    for v in violations:
        where = f"#{v['event_index']}"
        if v["line_no"]:
            where += f" {v['line_no']}행"
        mark = "자동" if v["auto_fixable"] else "확인"
        out.append(f"  [{mark}] {where:>10}  {v['rule_id']} {v['clause']}")
        out.append(f"              {v['message']}")
        if v["detail"]:
            out.append(f"              -> {v['detail']}")

    out.append("")
    out.append(f"  위반 {len(violations)}건")
    if report["unimplemented_checks"]:
        # 검사하지 않은 것을 통과로 보이게 하지 않는다.
        out.append(f"  미구현 검사 {len(report['unimplemented_checks'])}건: "
                   + ", ".join(report["unimplemented_checks"]))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="checker", description="플랫폼 규정 준수 검사")
    ap.add_argument("file", nargs="?", type=Path, help="자막 파일 (.srt / .vtt)")
    ap.add_argument("-p", "--platform", default="netflix")
    ap.add_argument("-l", "--lang", default="ko")
    ap.add_argument("-k", "--kind", choices=["sdh", "translation"], default="translation")
    ap.add_argument("--children", action="store_true", help="아동 프로그램 기준 적용")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--list", action="store_true", help="쓸 수 있는 프로파일 목록")
    args = ap.parse_args(argv)

    if args.list:
        for platform, lang, kind in available_profiles():
            print(f"{platform:10} {lang:4} {kind}")
        return 0

    if not args.file:
        ap.error("자막 파일이 필요합니다 (또는 --list)")
    if not args.file.is_file():
        print(f"파일이 없습니다: {args.file}", file=sys.stderr)
        return 2

    try:
        profile = load_profile(args.platform, args.lang, args.kind)
    except ProfileError as e:
        print(f"프로파일 오류: {e}", file=sys.stderr)
        return 2

    events = parse(args.file)
    if not events:
        print(f"자막 이벤트를 읽지 못했습니다: {args.file}", file=sys.stderr)
        return 2

    report = check_events([e.__dict__ for e in events], profile, children=args.children)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_format_text(report, args.file))

    return 1 if report["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
