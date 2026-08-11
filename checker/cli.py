"""명령줄 진입점.

    python -m checker examples/sample.srt --platform netflix --lang ko --kind sdh
    python -m checker file.srt -p netflix -l en -k translation --json
    python -m checker 시즌1/ -l ko -k sdh --fix        # 폴더 통째로
    python -m checker --list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import check_events, available_profiles, load_profile, ProfileError
from .profile import load_profile_file
from .fixes import apply_fixes
from .korean import CorrectorUnavailable, load_backend, run_korean_pass
from .parsers import parse
from .writers import write_srt

SUBTITLE_SUFFIXES = (".srt", ".vtt")


def _format_text(report: dict, path: Path) -> str:
    # 어떤 틀로 쟀는지가 결과만큼 중요하다. 발주처가 다르면 정답도 달라진다.
    out = [f"{path.name} — {report['profile']} {report['kind']}"]
    if report.get("profile_source"):
        out.append(f"  기준: {report['profile_source']}")
    violations = report["violations"]
    if not violations:
        out.append("  위반 없음")
    for v in violations:
        where = f"#{v['event_index']}"
        if v["line_no"]:
            where += f" {v['line_no']}행"
        mark = "자동" if v["auto_fixable"] else "확인"
        origin = "" if v.get("source", "rule") == "rule" else f" ({v['source']})"
        out.append(f"  [{mark}] {where:>10}  {v['rule_id']} {v['clause']}{origin}")
        if v.get("text"):
            out.append(f"              | {v['text']}")
        out.append(f"              {v['message']}")
        if v["detail"]:
            out.append(f"              {v['detail'] if v['detail'].startswith('->') else '-> ' + v['detail']}")

    out.append("")
    if violations:
        # 규칙별 집계 — 같은 문제가 몇 번 나는지 보여야 어디부터 손댈지 정한다.
        counts: dict[tuple[str, str], int] = {}
        for v in violations:
            counts[(v["rule_id"], v["message"])] = counts.get((v["rule_id"], v["message"]), 0) + 1
        out.append("  규칙별 집계")
        for (rule_id, message), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0][0])):
            out.append(f"    {n:>4}건  {rule_id}  {message}")
        out.append("")
    out.append(f"  위반 {len(violations)}건")
    if report.get("spot_suggestions"):
        out.append(f"  스포팅 제안 {len(report['spot_suggestions'])}건 (자동 적용 안 함)")
        for sug in report["spot_suggestions"][:8]:
            out.append(f"    #{sug['event_index']} {sug['field']} "
                       f"{sug['current']} -> {sug['suggested']}ms  ({sug['reason']})")
        if len(report["spot_suggestions"]) > 8:
            out.append(f"    … 외 {len(report['spot_suggestions']) - 8}건")

    if report.get("timing_changes") is not None:
        out.append(f"  타임코드 {len(report['timing_changes'])}곳 조정")
        for c in report["timing_changes"][:8]:
            out.append(f"    #{c['event_index']} {c['field']} "
                       f"{c['before']} -> {c['after']}ms  ({c['reason']})")
        if len(report["timing_changes"]) > 8:
            out.append(f"    … 외 {len(report['timing_changes']) - 8}곳")
        for u in report.get("timing_unresolved", []):
            # 못 맞춘 것을 맞췄다고 하지 않는다.
            out.append(f"    [남음] #{u['event_index']} {u['message']}")

    if report.get("fixed_file"):
        out.append(f"  교정본: {report['fixed_file']}")
        if report["applied_fixes"]:
            out.append(f"  적용한 자동 교정: {', '.join(report['applied_fixes'])}")
        if report["auto_but_unfixable"]:
            # 고쳤다고 말하지 않는다.
            out.append("  자동 표시지만 기계가 못 고치는 것: "
                       + ", ".join(report["auto_but_unfixable"]))
    if report["unimplemented_checks"]:
        # 검사하지 않은 것을 통과로 보이게 하지 않는다.
        out.append(f"  미구현 검사 {len(report['unimplemented_checks'])}건: "
                   + ", ".join(report["unimplemented_checks"]))
    return "\n".join(out)


def _force_utf8_output() -> None:
    """Windows 콘솔 기본 인코딩(cp949)에서 리포트가 깨지지 않게 한다.

    편집기는 Windows에서 돌아갈 가능성이 높은데, 한국어 규정 문구에는 cp949로
    표현할 수 없는 문자(—, ♪, …)가 들어 있다. 출력이 예외로 죽지 않아야 한다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def collect_files(targets: list[Path]) -> list[Path]:
    """파일과 폴더를 섞어 받아 자막 파일 목록으로 편다.

    폴더는 한 단계만 훑는다 — 회차 파일이 한 폴더에 모여 있는 실제 작업 형태에
    맞추고, 교정 결과(`*.fixed.srt`)를 다시 집어 들지 않게 거른다.
    """
    files: list[Path] = []
    for target in targets:
        if target.is_dir():
            found = [
                p for p in sorted(target.iterdir())
                if p.suffix.lower() in SUBTITLE_SUFFIXES and not p.name.endswith(".fixed.srt")
            ]
            files.extend(found)
        elif target.is_file():
            files.append(target)
        else:
            print(f"파일이 없습니다: {target}", file=sys.stderr)
    return files


def _run_one(path: Path, profile: dict, args, backend) -> dict | None:
    from .timing import TimingLimits, converge

    events = parse(path)
    if not events:
        print(f"자막 이벤트를 읽지 못했습니다: {path}", file=sys.stderr)
        return None

    timing = None
    if getattr(args, "fix_timing", False):
        limits = TimingLimits.from_profile(profile, fps=args.fps, children=args.children)
        timing = converge(events, limits)
        events = timing.events

    report = check_events([e.__dict__ for e in events], profile,
                          children=args.children, fps=args.fps)
    report["file"] = str(path)
    if getattr(args, "spot", False) and getattr(args, "_media", None):
        from .media import MediaToolUnavailable, detect_speech
        from .timing import suggest_spotting
        try:
            speech = detect_speech(args.video, duration_ms=args._media.duration_ms)
        except MediaToolUnavailable as e:
            print(f"말소리 검출을 건너뜁니다: {e}", file=sys.stderr)
        else:
            suggestions = suggest_spotting(events, speech, args._media.fps)

            # 장면 전환은 플랫폼이 적용할 때만 본다(쿠팡은 비적용).
            if (profile.get("shot_change") or {}).get("applied"):
                from .media import detect_shot_changes
                from .timing import suggest_shot_snap
                shots = detect_shot_changes(args.video)
                print(f"    장면 전환 {len(shots)}곳", file=sys.stderr)
                suggestions += suggest_shot_snap(events, shots, args._media.fps)

            report["spot_suggestions"] = [
                {"event_index": s.event_index, "field": s.field_name,
                 "current": s.current, "suggested": s.suggested, "reason": s.reason}
                for s in suggestions]

    if timing is not None:
        report["timing_changes"] = [
            {"event_index": c.event_index, "field": c.field_name,
             "before": c.before, "after": c.after, "reason": c.reason}
            for c in timing.changes]
        report["timing_unresolved"] = [
            {"event_index": i, "message": m} for i, m in timing.unresolved]

    ko_fixed = None
    if backend is not None:
        ko_fixed, ko_violations = run_korean_pass(events, backend, spacing_mode=args.spacing)
        report["violations"].extend(v.to_dict() for v in ko_violations)
        report["violations"].sort(key=lambda v: (v["event_index"], v["rule_id"]))

    if args.fix:
        fixed, applied, unfixable = apply_fixes(events, profile)
        if ko_fixed is not None:
            # 교정기 결과를 규정 자동 교정 위에 얹는다. 순서를 바꾸면 교정기가
            # 넣은 문장부호를 규정 교정이 다시 걷어내는 왕복이 생긴다.
            fixed, applied2, _ = apply_fixes(ko_fixed, profile)
            applied = sorted(set(applied) | set(applied2))
        out_path = args.out or path.with_suffix(".fixed.srt")
        write_srt(fixed, out_path)
        report["fixed_file"] = str(out_path)
        report["applied_fixes"] = applied
        report["auto_but_unfixable"] = unfixable

    return report


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser(prog="checker", description="플랫폼 규정 준수 검사")
    ap.add_argument("targets", nargs="*", type=Path,
                    help="자막 파일 또는 폴더 (.srt / .vtt). 여러 개 줄 수 있다")
    ap.add_argument("--profile", type=Path,
                    help="프로파일 파일을 직접 지정한다(발주처 기준·템플릿 등). "
                         "--list로 이름을 확인한다")
    ap.add_argument("-p", "--platform", default="netflix")
    ap.add_argument("-l", "--lang", default="ko")
    ap.add_argument("-k", "--kind", choices=["sdh", "translation"], default="translation")
    ap.add_argument("--children", action="store_true", help="아동 프로그램 기준 적용")
    ap.add_argument("--video", type=Path,
                    help="영상 파일. 프레임레이트를 자동으로 읽고 --spot에 쓴다(ffmpeg 필요)")
    ap.add_argument("--spot", action="store_true",
                    help="말소리 구간과 견줘 인점·아웃점을 제안한다(자동 교정 아님)")
    ap.add_argument("--fps", type=float, default=23.976,
                    help="영상 프레임레이트. 자막 간격 같은 프레임 단위 규정을 환산한다")
    ap.add_argument("--json", action="store_true", help="JSON으로 출력")
    ap.add_argument("--list", action="store_true", help="쓸 수 있는 프로파일 목록")
    ap.add_argument("--korean", action="store_true",
                    help="한국어 교정기 레인을 함께 돌린다(맞춤법·띄어쓰기)")
    ap.add_argument("--ksc-path", help="한국어 교정기 저장소 경로(기본: 환경변수 KSC_PATH)")
    ap.add_argument("--spacing", choices=["principle", "allowance"], default="principle",
                    help="보조 용언 띄어쓰기 기준(제47항). 교정기 레인에만 쓴다")
    ap.add_argument("--fix-timing", action="store_true",
                    help="타임코드를 규정에 맞게 수렴시킨다(영상 없이 됨). --fix와 함께 쓰면 "
                         "교정본에 함께 반영된다")
    ap.add_argument("--fix", action="store_true",
                    help="자동 교정 가능한 것을 고쳐 새 파일로 쓴다(원본은 그대로)")
    ap.add_argument("-o", "--out", type=Path,
                    help="교정 결과 경로(기본: <원본>.fixed.srt). 파일 하나일 때만 쓴다")
    ap.add_argument("--report", type=Path,
                    help="리포트를 파일로도 남긴다(화면 출력은 그대로 나온다)")
    args = ap.parse_args(argv)

    if args.list:
        for prof in available_profiles():
            extra = f"  {prof['section']}" if prof["section"] else ""
            rev = f" ({prof['revision']})" if prof["revision"] else ""
            print(f"{prof['name']:18} {prof['platform']:8} {prof['language']:3} "
                  f"{prof['kind']:12}{extra}{rev}")
        return 0

    if not args.targets:
        ap.error("자막 파일이나 폴더가 필요합니다 (또는 --list)")

    files = collect_files(args.targets)
    if not files:
        print("검사할 자막 파일이 없습니다.", file=sys.stderr)
        return 2

    # 영상을 안 줬는데 스포팅을 원하면 자막 옆에서 같은 이름을 찾는다.
    # **영상을 읽기 전에** 찾아야 한다 — 순서가 바뀌면 자동으로 찾은 영상을 못 읽는다.
    if args.spot and not args.video:
        from .media import find_video_for
        guess = find_video_for(files[0])
        if guess:
            args.video = guess
            print(f"영상을 찾았습니다: {guess.name}", file=sys.stderr)
        else:
            print("옆에 같은 이름의 영상이 없습니다. --video로 지정하세요.", file=sys.stderr)

    media = None
    if args.video:
        from .media import MediaToolUnavailable, probe
        try:
            media = probe(args.video)
        except MediaToolUnavailable as e:
            print(f"영상을 읽지 못했습니다: {e}", file=sys.stderr)
        else:
            # --fps를 손으로 준 경우가 아니면 영상 값을 쓴다
            if "--fps" not in (argv or sys.argv[1:]):
                args.fps = media.fps
            print(f"영상: {media.width}x{media.height}, {media.fps:g}fps, "
                  f"{media.duration_ms / 1000:.1f}초", file=sys.stderr)
            if media.variable_frame_rate:
                print("  주의: 프레임레이트가 일정하지 않습니다(화면 녹화물 등)."
                      " 프레임 단위 규정 환산이 어긋날 수 있습니다.", file=sys.stderr)

    if args.out and len(files) > 1:
        print("-o는 파일 하나일 때만 씁니다.", file=sys.stderr)
        return 2

    try:
        profile = (load_profile_file(args.profile) if args.profile
                   else load_profile(args.platform, args.lang, args.kind))
    except ProfileError as e:
        print(f"프로파일 오류: {e}", file=sys.stderr)
        return 2

    # 교정기는 한 번만 올린다 — 형태소 분석기 적재가 무거워서 파일마다 올리면
    # 회차를 여러 개 돌릴 때 그 비용이 그대로 곱해진다.
    backend = None
    if args.korean:
        if args.lang != "ko":
            print("한국어 교정 레인은 --lang ko 에서만 씁니다.", file=sys.stderr)
            return 2
        print("한국어 교정기를 올리는 중입니다. 형태소 분석기 적재에 1~2분 걸립니다...",
              file=sys.stderr, flush=True)
        try:
            backend = load_backend(args.ksc_path)
            print("한국어 교정기 준비 완료.", file=sys.stderr, flush=True)
        except CorrectorUnavailable as e:
            # 못 돌렸다는 사실을 숨기지 않는다 — 통과로 보이면 안 된다.
            print(f"한국어 교정 레인을 건너뜁니다: {e}", file=sys.stderr)

    args._media = media
    reports = []
    for n, path in enumerate(files, 1):
        print(f"[{n}/{len(files)}] {path.name} 검사 중...", file=sys.stderr, flush=True)
        report = _run_one(path, profile, args, backend)
        if report is not None:
            reports.append(report)

    if not reports:
        return 2

    if args.json:
        output = json.dumps(reports if len(reports) > 1 else reports[0],
                            ensure_ascii=False, indent=2)
    else:
        blocks = [_format_text(r, Path(r["file"])) for r in reports]
        if len(reports) > 1:
            total = sum(len(r["violations"]) for r in reports)
            clean = sum(1 for r in reports if not r["violations"])
            blocks.append(f"합계: 파일 {len(reports)}개, 위반 {total}건, "
                          f"위반 없는 파일 {clean}개")
        output = "\n\n".join(blocks)

    print(output)
    if args.report:
        args.report.write_text(output + "\n", encoding="utf-8")
        print(f"\n리포트를 저장했습니다: {args.report}")

    return 1 if any(r["violations"] for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
