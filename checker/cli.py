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
from .writers import write_review_srt, write_srt

SUBTITLE_SUFFIXES = (".srt", ".vtt")


def _format_text(report: dict, path: Path) -> str:
    # 어떤 틀로 쟀는지가 결과만큼 중요하다. 발주처가 다르면 정답도 달라진다.
    out = [f"{path.name} — {report['profile']} {report['kind']}"]
    if report.get("profile_source"):
        out.append(f"  기준: {report['profile_source']}")
    if report.get("profile_warning"):
        out.append(f"  ⚠ {report['profile_warning']}")
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
    if report.get("translated_file"):
        out.append(f"  한국어 초벌: {report['translated_file']}")
        notes = report.get("translation_notes") or []
        if notes:
            out.append(f"    확인이 필요한 자리 {len(notes)}곳: "
                       + ", ".join(f"#{n['event_index']}" for n in notes[:8]))
    if report.get("timecodes_locked"):
        out.append("  타임코드 고정: 받은 타임코드를 그대로 둡니다(나누기·수렴·스포팅 안 함)")
    if report.get("lock_violation"):
        out.append(f"  [오류] {report['lock_violation']}")
    if report.get("spotting_applied"):
        out.append(f"  인점·아웃점 {report['spotting_applied']}곳을 말소리에 맞춰 옮겼습니다")
    if report.get("spot_suggestions"):
        applied = "적용함" if report.get("spotting_applied") else "자동 적용 안 함"
        out.append(f"  스포팅 제안 {len(report['spot_suggestions'])}건 ({applied})")
        for sug in report["spot_suggestions"][:8]:
            out.append(f"    #{sug['event_index']} {sug['field']} "
                       f"{sug['current']} -> {sug['suggested']}ms  ({sug['reason']})")
        if len(report["spot_suggestions"]) > 8:
            out.append(f"    … 외 {len(report['spot_suggestions']) - 8}건")

    if report.get("job_note"):
        out.append(f"  ⚠ {report['job_note']}")
    if report.get("position_suggestions"):
        found = report["position_suggestions"]
        out.append(f"  위치 제안 {len(found)}건 (영상 추정이라 자동 적용 안 함)")
        for sug in found[:8]:
            out.append(f"    #{sug['event_index']} {sug['reason']}")
        if len(found) > 8:
            out.append(f"    … 외 {len(found) - 8}건")

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

    if report.get("review_file"):
        out.append(f"  검토용 자막: {report['review_file']}")
        out.append("    SE에서 원본을 열고 '파일 - 원본 자막 열기'로 이 파일을 얹으면"
                   " 그리드에 나란히 보입니다")

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


def _timecodes_of(events) -> list[tuple[int, int, int]]:
    return [(e.index, e.start_ms, e.end_ms) for e in events]


def _assert_timecodes_unchanged(before, after, path: Path) -> str | None:
    """정말 안 움직였는지 확인한다.

    "건드리지 않기로 했다"는 약속은 지켰는지 확인할 수 있어야 약속이다. 어딘가에서
    한 줄만 옮겨도 납품물이 반려된다 — 사람이 눈으로 찾기 전에 기계가 잡는다.
    """
    if before == after:
        return None
    moved = [b[0] for b, a in zip(before, after) if b != a]
    if len(after) != len(before):
        return (f"타임코드를 고정했는데 자막 개수가 {len(before)}개에서 {len(after)}개로 "
                f"바뀌었습니다. 결과를 쓰지 않았습니다: {path.name}")
    return (f"타임코드를 고정했는데 {len(moved)}곳이 움직였습니다"
            f"(#{', #'.join(str(i) for i in moved[:5])}). 결과를 쓰지 않았습니다.")


def _run_one(path: Path, profile: dict, args, backend) -> dict | None:
    from .timing import TimingLimits, converge

    events = parse(path)
    if not events:
        print(f"자막 이벤트를 읽지 못했습니다: {path}", file=sys.stderr)
        return None

    locked = getattr(args, "lock_timecodes", False)
    original_tc = _timecodes_of(events) if locked else None

    timing = None
    if getattr(args, "fix_timing", False):
        limits = TimingLimits.from_profile(profile, fps=args.fps, children=args.children)
        timing = converge(events, limits)
        events = timing.events

    # 영상이 있으면 화면 아래쪽에 글자가 타 있는 구간을 찾아 위치 규칙에 쓴다.
    # 한 번의 ffmpeg 통과로 끝나고, 결과는 **제안에만** 쓴다(무늬를 글자로 볼 수 있다).
    busy_spans = None
    if getattr(args, "video", None) and getattr(args, "_media", None):
        from .media import MediaToolUnavailable, detect_bottom_text
        try:
            busy_spans = detect_bottom_text(args.video)
        except MediaToolUnavailable as e:
            print(f"화면 글자 검출을 건너뜁니다: {e}", file=sys.stderr)
        else:
            if busy_spans:
                print(f"    화면 아래 글자로 보이는 구간 {len(busy_spans)}곳", file=sys.stderr)

    from .position import JobRules
    rules = JobRules.from_profile(profile, {
        "marker": getattr(args, "fn_marker", None),
        "policy": getattr(args, "collision", None),
        "move_to": getattr(args, "collision_move_to", None),
    })

    report = check_events([e.__dict__ for e in events], profile,
                          children=args.children, fps=args.fps,
                          busy_spans=busy_spans, job_rules=rules)
    report["file"] = str(path)
    if locked:
        report["timecodes_locked"] = True

    note = rules.undecided_note()
    if note:
        report["job_note"] = note

    # 영상 근거는 자동 교정에 쓰지 않는다. 사람이 볼 수 있게 따로 낸다.
    if busy_spans:
        from .position import suggest_positions
        guesses = [s for s in suggest_positions(events, profile, busy_spans, rules)
                   if not s.certain]
        if guesses:
            report["position_suggestions"] = [
                {"event_index": s.event_index, "reason": s.reason} for s in guesses]

    # 프로파일을 잘못 고르면 지적이 통째로 뒤집힌다. 자막 표기로 유추해 어긋나면 알린다.
    from .detect import mismatch_warning
    warning = mismatch_warning(events, profile)
    if warning:
        report["profile_warning"] = warning
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

            if getattr(args, "fix_spotting", False) and not args.lock_timecodes:
                from .timing import apply_spotting
                moved = apply_spotting(events, suggestions)
                report["spotting_applied"] = moved
                # 무엇을 덮어썼는지 남긴다. 되돌릴 근거가 있어야 한다.
                print(f"    인점·아웃점 {moved}곳을 말소리에 맞춰 옮겼습니다",
                      file=sys.stderr)

            report["spot_suggestions"] = [
                {"event_index": s.event_index, "field": s.field_name,
                 "current": s.current, "suggested": s.suggested, "reason": s.reason}
                for s in suggestions]

    if getattr(args, "review_srt", False):
        review_path = path.with_suffix(".review.srt")
        write_review_srt(events, report["violations"], review_path)
        report["review_file"] = str(review_path)

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

    if getattr(args, "translate", False) and not getattr(args, "generate", False):
        # **받은 TC에 번역만 얹는 작업.** 실무에서 가장 흔한 형태다
        # (작업자 자료 190행: "TC 작업이 되어 온 파일에 내가 번역만 한 경우는
        # TC를 절대 건드리면 안 됨!").
        #
        # 이때는 재분할을 하지 않는다. 나누면 경계가 새로 생기기 때문이다. 대신
        # 주어진 칸 안에 들어가지 않는 한국어는 **검사가 잡아** 사람이 줄인다.
        from .translate import Glossary, TranslatorUnavailable, make_translator
        from .translate import to_events, translate_events
        try:
            translator = make_translator(args.translate_model or "exaone3.5:7.8b")
        except TranslatorUnavailable as exc:
            print(f"[오류] {exc}", file=sys.stderr)
            return report
        glossary = Glossary.from_profile(profile)
        if getattr(args, "glossary", None):
            glossary.merge_file(args.glossary)
        print(f"    한국어로 옮깁니다 — 자막 {len(events)}개", file=sys.stderr)
        cues = translate_events(events, translator, glossary,
                                progress=lambda m: print(f"    {m}", file=sys.stderr))
        translated = to_events(cues, events)
        out_path = args.out or path.with_suffix(".ko.srt")
        write_srt(translated, out_path)
        report["translated_file"] = str(out_path)
        report["translation_notes"] = [
            {"event_index": c.index, "note": c.note} for c in cues if c.note]
        # 번역본은 타임코드를 그대로 물려받는다. 그것을 확인해 둔다.
        problem = _assert_timecodes_unchanged(
            _timecodes_of(events), _timecodes_of(translated), path)
        if problem:
            report["lock_violation"] = problem

    if args.fix:
        fixed, applied, unfixable = apply_fixes(events, profile, rules)
        if ko_fixed is not None:
            # 교정기 결과를 규정 자동 교정 위에 얹는다. 순서를 바꾸면 교정기가
            # 넣은 문장부호를 규정 교정이 다시 걷어내는 왕복이 생긴다.
            fixed, applied2, _ = apply_fixes(ko_fixed, profile, rules)
            applied = sorted(set(applied) | set(applied2))
        # 고정하기로 했으면 **쓰기 전에** 확인한다. 쓰고 나서 알면 늦다.
        if original_tc is not None:
            problem = _assert_timecodes_unchanged(
                original_tc, _timecodes_of(fixed), path)
            if problem:
                report["lock_violation"] = problem
                print(f"[오류] {problem}", file=sys.stderr)
                return report

        out_path = args.out or path.with_suffix(".fixed.srt")
        write_srt(fixed, out_path)
        report["fixed_file"] = str(out_path)
        report["applied_fixes"] = applied
        report["auto_but_unfixable"] = unfixable

    return report


def _generate_mode(args, ap) -> int:
    """영상 -> 자막 초안. 검사 경로와 섞지 않는다 — 입력도 출력도 다르다."""
    from .generate import generate, notes_srt
    from .media import MediaToolUnavailable

    if not args.video:
        ap.error("--generate에는 --video가 필요합니다")
    if not args.video.is_file():
        ap.error(f"영상을 찾지 못했습니다: {args.video}")

    profile = (load_profile_file(args.profile) if args.profile
               else load_profile(args.platform, args.lang, args.kind))
    print(f"프로파일: {profile.get('platform')} {profile.get('language')} "
          f"{profile.get('kind')}")

    translator = glossary = None
    if args.translate:
        from .translate import Glossary, TranslatorUnavailable, make_translator
        try:
            translator = make_translator(args.translate_model or "exaone3.5:7.8b")
        except TranslatorUnavailable as exc:
            print(f"[오류] {exc}")
            return 2
        glossary = Glossary.from_profile(profile)
        if args.glossary:
            glossary.merge_file(args.glossary)
            print(f"표기 통일표 {len(glossary.terms)}개를 적용합니다")

    out = args.out or args.video.with_suffix(".draft.srt")
    try:
        draft = generate(args.video, profile, script=args.script,
                         language=args.whisper_lang, model=args.whisper_model,
                         fps=None, use_gpu=not args.cpu, translator=translator,
                         glossary=glossary,
                         keep_source=out.with_suffix(".source.srt") if translator else None,
                         progress=print)
    except MediaToolUnavailable as exc:
        print(f"[오류] {exc}")
        return 2

    if not draft.events:
        print("말소리를 찾지 못했습니다.")
        return 1

    write_srt(draft.events, out)
    print(f"\n자막 초안을 저장했습니다: {out}  (자막 {len(draft.events)}개)")

    if draft.notes:
        notes_path = out.with_suffix(".notes.srt")
        notes_path.write_text(notes_srt(draft), encoding="utf-8")
        print(f"봐야 할 자리 {len(draft.notes)}곳: {notes_path}")
        print("  SE에서 초안을 연 뒤 [파일 - 원본 자막 열기]로 이 파일을 얹으면 "
              "나란히 보입니다.")

    print("\n초안입니다. 사람이 보고 고치는 것을 전제로 만들었습니다. "
          "이어서 검사를 돌리려면:")
    print(f"  checker \"{out}\" -p {args.platform} -k {args.kind} --korean")
    return 0


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
    ap.add_argument("--lock-timecodes", action="store_true",
                    help="**타임코드를 절대 건드리지 않는다.** TC 작업이 끝난 파일을 "
                         "받아 번역·교정만 할 때 쓴다. 자막을 나누는 것도 막는다"
                         "(나누면 경계가 새로 생긴다)")
    ap.add_argument("--fix-spotting", action="store_true",
                    help="제안을 **자동으로 반영한다**. 사람이 잡아 놓은 타임코드도 "
                         "덮어쓰므로, 남이 준 TC 파일에는 쓰지 말 것. --fix와 함께 쓴다")
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
    ap.add_argument("--review-srt", action="store_true",
                    help="지적을 자막 파일로도 낸다(<원본>.review.srt). SE 번역 모드로 "
                         "원본 옆에 띄워 영상을 보며 확인할 수 있다")
    job = ap.add_argument_group(
        "작업 기준", "작업마다 달라지는 것들. **작업 시작 전에 정한다** — "
                  "정하지 않으면 위치 검사는 하지 않는다(추측해서 옮기지 않는다)")
    job.add_argument("--fn-marker",
                     choices=["double_quote", "italic", "bracket", "none"],
                     help="화면자막을 말자막과 구분하는 표식")
    job.add_argument("--collision",
                     choices=["move_dialogue", "dialogue_only", "keep_both"],
                     help="말자막과 화면자막이 겹칠 때: 말자막을 옮긴다 / "
                          "말자막만 남긴다(영상번역 기본) / 둘 다 둔다")
    job.add_argument("--collision-move-to",
                     choices=["top_left", "top_center", "top_right",
                              "bottom_left", "bottom_center", "bottom_right"],
                     help="--collision move_dialogue일 때 말자막을 보낼 자리")
    ap.add_argument("--report", type=Path,
                    help="리포트를 파일로도 남긴다(화면 출력은 그대로 나온다)")
    gen = ap.add_argument_group(
        "자막 만들기", "검사가 아니라 **생성**이다. --video만 주면 SDH 초안, "
                    "--script를 함께 주면 원어 대조까지 한다")
    gen.add_argument("--generate", action="store_true",
                     help="영상에서 자막 초안을 만든다(whisper 전사 -> 재분할 -> 스포팅)")
    gen.add_argument("--script", type=Path,
                     help="원어 스크립트. 전사와 대조해 텍스트를 정한다. "
                          "어느 쪽도 정답으로 두지 않고 어긋난 자리는 표시한다")
    gen.add_argument("--whisper-model",
                     help="ggml 모델 경로(기본: WHISPER_MODEL 환경변수 또는 models/ 폴더의 "
                          "가장 큰 것). large-v3-turbo 권장")
    gen.add_argument("--whisper-lang", default="auto",
                     help="말소리 언어(ko, en, auto…). 아는 값을 주면 정확해진다")
    gen.add_argument("--cpu", action="store_true",
                     help="GPU를 쓰지 않는다(느리다). 기본은 GPU")
    gen.add_argument("--translate", action="store_true",
                     help="원어를 한국어 초벌로 옮긴다. 모델은 이 컴퓨터에서 돈다"
                          "(원고가 밖으로 나가지 않는다)")
    gen.add_argument("--translate-model",
                     help="번역에 쓸 로컬 모델(기본: exaone3.5:7.8b). "
                          "`ollama list`에 있는 이름")
    gen.add_argument("--glossary", type=Path,
                     help="표기 통일표. `원어=한국어` 한 줄에 하나. "
                          "발주처가 주는 표를 그대로 쓴다")
    args = ap.parse_args(argv)

    if args.generate:
        return _generate_mode(args, ap)

    if args.list:
        for prof in available_profiles():
            extra = f"  {prof['section']}" if prof["section"] else ""
            rev = f" ({prof['revision']})" if prof["revision"] else ""
            print(f"{prof['name']:18} {prof['platform']:8} {prof['language']:3} "
                  f"{prof['kind']:12}{extra}{rev}")
        return 0

    if args.lock_timecodes:
        # 조용히 무시하면 사람은 고정된 줄 알고, 기계는 옮긴다. 둘 중 더 나쁜 쪽이다.
        clash = [name for name, on in (("--fix-timing", args.fix_timing),
                                       ("--fix-spotting", args.fix_spotting)) if on]
        if clash:
            ap.error(f"--lock-timecodes와 {', '.join(clash)}은(는) 함께 쓸 수 없습니다. "
                     f"받은 타임코드를 지킬지 고칠지 먼저 정하세요")

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
