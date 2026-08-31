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

from . import available_profiles, load_profile, ProfileError
from . import genre as _genre
from .profile import load_profile_file
from .korean import CorrectorUnavailable, load_backend
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
    if report.get("revision_rounds"):
        rows = report["revision_rounds"]
        out.append("  감수 회차: "
                   + ", ".join(f"{r['stage']}({r['role']}) {r['changed']}곳" for r in rows))
        out.append(f"    {report.get('revision_stopped_because', '')}")
    if report.get("mistranslation_flags"):
        flags = report["mistranslation_flags"]
        counts = report.get("mistranslation_summary") or {}
        out.append(f"  1차 번역에서 확인이 필요한 자리 {len(flags)}곳 "
                   f"(확정 {counts.get('certain', 0)} · 추정 {counts.get('estimated', 0)}) "
                   f"— 규정 위반이 아닙니다")
        labels = {"speaker": "화자 표시", "glossary": "용어", "negation": "부정",
                  "number": "숫자"}
        for flag in flags[:10]:
            mark = "확정" if flag["certain"] else "추정"
            out.append(f"    [{mark}] #{flag['event_index']} "
                       f"{labels.get(flag['kind'], flag['kind'])} — {flag['reason']}")
            if flag.get("source"):
                out.append(f"           원문 {flag['source'][:60]}")
                out.append(f"           번역 {flag['target'][:60]}")
        if len(flags) > 10:
            out.append(f"    … 외 {len(flags) - 10}곳")
    if report.get("backtranslation"):
        bt = report["backtranslation"]
        stats, rows = bt["summary"], bt["worst"]
        out.append(f"  역번역 대조 — 견준 자막 {stats.get('total', 0)}개, 원문 낱말이 "
                   f"남은 비율 중간값 {stats.get('median', 0):.0%}, "
                   f"절반도 안 남은 자막 {stats.get('below_half', 0)}개")
        # **판정이 아니라 순위다.** 몇 점 이하가 오역인지는 실제 작업물로 재야 안다.
        out.append("    점수가 낮은 순입니다(판정이 아니라 순위 — 기준선이 없습니다)")
        for row in rows[:8]:
            out.append(f"    #{row['event_index']} {row['score']:.0%}"
                       + (f"  빠진 낱말: {', '.join(row['missing'][:5])}"
                          if row["missing"] else ""))
            out.append(f"           원문   {row['source'][:60]}")
            out.append(f"           번역   {row['korean'][:60]}")
            out.append(f"           역번역 {row['back'][:60]}")
        if len(rows) > 8:
            out.append(f"    … 외 {len(rows) - 8}개")
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

    if report.get("genre"):
        src = report.get("genre_source") or {}
        out.append(f"  장르: {report['genre']}"
                   + (f" ({src.get('section')} — {src.get('client', '')})" if src else ""))
    # **권장이지 규정이 아니다.** 위반 건수에 섞지 않는다.
    if report.get("off_recommendation"):
        off = report["off_recommendation"]
        out.append(f"  권장 표시 시간을 벗어난 자막 {len(off)}개 "
                   f"(규정 위반은 아닙니다 — {off[0]['note']})")
        for row in off[:8]:
            out.append(f"    #{row['event_index']} {row['reason']}")
        if len(off) > 8:
            out.append(f"    … 외 {len(off) - 8}개")
    if report.get("formality"):
        fm = report["formality"]
        ratio = fm.get("formal_ratio")
        if ratio is None:
            out.append(f"  말투: 확정된 종결어미가 없어 재지 못했습니다"
                       f"(유보 {fm['undecided']}개)")
        else:
            # **판정하지 않는다.** '가끔 요를 쓰는 것은 허용된다'는 확인을 받았고,
            # 몇 퍼센트까지가 '가끔'인지는 완성본으로 재기 전까지 모른다.
            out.append(f"  말투: {fm['prefer']} 권장 — 합니다체 {ratio:.0%} "
                       f"(합니다체 {fm['counts']['합니다체']} / "
                       f"해요체 {fm['counts']['해요체']}, 유보 {fm['undecided']})")
            if fm["counts"]["해요체"]:
                out.append("    해요체가 섞인 것은 허용됩니다. 기준선이 없어 "
                           "판정하지 않고 숫자만 냅니다.")
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
        # 검사는 교정한 자막을 설명하므로 고쳐진 위반은 위 목록에 없다. 무엇을
        # 고쳤는지는 여기서 본다.
        changes = report.get("text_changes") or []
        if changes:
            source = (f", 한국어 교정 {report['korean_changed']}곳 포함"
                      if report.get("korean_changed") else "")
            out.append(f"  글자를 고친 자막 {len(changes)}개{source}")
            for c in changes[:8]:
                out.append(f"    #{c['event_index']} {c['before']} -> {c['after']}")
            if len(changes) > 8:
                out.append(f"    … 외 {len(changes) - 8}개")
        if report["auto_but_unfixable"]:
            # 고쳤다고 말하지 않는다.
            out.append("  자동 표시지만 기계가 못 고치는 것: "
                       + ", ".join(report["auto_but_unfixable"]))
    if report["unimplemented_checks"]:
        # 검사하지 않은 것을 통과로 보이게 하지 않는다.
        out.append(f"  미구현 검사 {len(report['unimplemented_checks'])}건: "
                   + ", ".join(report["unimplemented_checks"]))
    # **구현은 돼 있는데 자료가 없어 못 돈 검사.** 미구현과 다르지만 숨기면 똑같이
    # "통과"로 보인다.
    for reason in report.get("skipped_checks") or []:
        out.append(f"  돌지 못한 검사: {reason}")
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

    # **스포팅은 검사보다 먼저다.** 타임코드를 옮기는 유일한 자리이므로, 뒤에 두면
    # 검사가 옮겨지기 전의 타임코드를 설명하게 된다.
    spot_suggestions = spotting_applied = None
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
                spotting_applied = apply_spotting(events, suggestions)
                # 무엇을 덮어썼는지 남긴다. 되돌릴 근거가 있어야 한다.
                print(f"    인점·아웃점 {spotting_applied}곳을 말소리에 맞춰 "
                      f"옮겼습니다", file=sys.stderr)

            spot_suggestions = suggestions

    # ------------------------------------------------------------ 교정과 검사
    # **순서는 `pipeline`이 정한다.** 어댑터마다 순서가 다르면 같은 자막에 다른
    # 리포트가 나온다 — 실제로 그랬다(교정이 만든 새 위반을 검사가 못 봤다).
    #
    # `--fix`가 없으면 파일을 쓰지 않으므로 교정문을 자막에 얹지 않는다. 얹고 검사하면
    # 리포트가 사용자가 가진 파일이 아니라 '고쳤다면 됐을 것'을 설명한다.
    from .pipeline import CorrectOptions, correct_and_check
    result = correct_and_check(events, profile, CorrectOptions(
        korean=backend is not None,
        backend=backend,
        apply_korean=bool(args.fix),
        spacing_mode=args.spacing,
        apply_fixes=bool(args.fix),
        children=args.children,
        fps=args.fps,
        busy_spans=busy_spans,
        job_rules=rules,
        cast=getattr(args, "_cast", None),
    ))
    fixed = result.events
    report = result.extra["report"]
    report["violations"] = result.violations
    report["file"] = str(path)
    if locked:
        report["timecodes_locked"] = True
    for note in result.notes:
        print(f"    {note}", file=sys.stderr)

    note = rules.undecided_note()
    if note:
        report["job_note"] = note

    if spotting_applied is not None:
        report["spotting_applied"] = spotting_applied
    if spot_suggestions is not None:
        report["spot_suggestions"] = [
            {"event_index": s.event_index, "field": s.field_name,
             "current": s.current, "suggested": s.suggested, "reason": s.reason}
            for s in spot_suggestions]

    # 영상 근거는 자동 교정에 쓰지 않는다. 사람이 볼 수 있게 따로 낸다.
    if busy_spans:
        from .position import suggest_positions
        guesses = [s for s in suggest_positions(fixed, profile, busy_spans, rules)
                   if not s.certain]
        if guesses:
            report["position_suggestions"] = [
                {"event_index": s.event_index, "reason": s.reason} for s in guesses]

    # 장르는 **권장이지 규정이 아니다.** 위반 목록에 넣지 않고 숫자로 낸다 —
    # 플랫폼이 정한 최소·최대(`limits`)를 어긴 것과 무게가 다르다(규칙 4·5).
    if profile.get("genre"):
        report["genre"] = profile["genre"]
        report["genre_source"] = profile.get("genre_source") or {}
        off = _genre.off_recommendation(fixed, profile)
        if off:
            report["off_recommendation"] = off
        # 다큐 합니다체 비율. **임계값을 두지 않았다** — '가끔 요를 쓰는 것은
        # 허용된다'는 확인을 받았고, 몇 퍼센트까지가 '가끔'인지는 완성본으로 재야 안다.
        prefer = (profile.get("formality") or {}).get("prefer")
        if prefer:
            from .formality import summary as _formality_summary
            report["formality"] = {"prefer": prefer, **_formality_summary(fixed)}

    # 프로파일을 잘못 고르면 지적이 통째로 뒤집힌다. 자막 표기로 유추해 어긋나면 알린다.
    from .detect import mismatch_warning
    warning = mismatch_warning(fixed, profile)
    if warning:
        report["profile_warning"] = warning

    # 검토용 자막은 **리포트가 설명하는 그 자막**에 지적을 얹는다.
    if getattr(args, "review_srt", False):
        review_path = path.with_suffix(".review.srt")
        write_review_srt(fixed, report["violations"], review_path)
        report["review_file"] = str(review_path)

    if timing is not None:
        report["timing_changes"] = [
            {"event_index": c.event_index, "field": c.field_name,
             "before": c.before, "after": c.after, "reason": c.reason}
            for c in timing.changes]
        report["timing_unresolved"] = [
            {"event_index": i, "message": m} for i, m in timing.unresolved]

    if getattr(args, "translate", False) and not getattr(args, "generate", False):
        # **받은 TC에 번역만 얹는 작업.** 실무에서 가장 흔한 형태다
        # (작업자 자료 190행: "TC 작업이 되어 온 파일에 내가 번역만 한 경우는
        # TC를 절대 건드리면 안 됨!").
        #
        # 이때는 재분할을 하지 않는다. 나누면 경계가 새로 생기기 때문이다. 대신
        # 주어진 칸 안에 들어가지 않는 한국어는 **검사가 잡아** 사람이 줄인다.
        from .pipeline import stage_revise, stage_translate
        from .translate import Glossary, TranslatorUnavailable, make_translator
        try:
            translator = make_translator(args.translate_model)
        except TranslatorUnavailable as exc:
            print(f"[오류] {exc}", file=sys.stderr)
            return report
        glossary = Glossary.from_profile(profile)
        if getattr(args, "glossary", None):
            glossary.merge_file(args.glossary)
        _add_knp(glossary, args, path)

        say = lambda m: print(f"    {m}", file=sys.stderr)   # noqa: E731

        # **깨졌을 때 처음부터 하지 않게 단계마다 남긴다.** 원본은 건드리지 않는다 —
        # 폴더를 따로 만들고 그 안에만 쓴다(규칙 7).
        work = None
        if not getattr(args, "no_work", False):
            from .work import Work
            work = Work.beside(path)
            work.save_source({e.index: e.text for e in events})

        import time as _time
        _began = _time.monotonic()
        first = stage_translate(events, profile, translator=translator,
                                glossary=glossary, progress=say)
        if work:
            work.save("02-first", first.events, model=translator.model,
                      seconds=_time.monotonic() - _began,
                      extra={"flags": len(first.extra.get("flags") or [])})
        translated = first.events
        report["translation_notes"] = first.extra["notes_by_index"]
        # **위반이 아니라 플래그다.** 부정·숫자는 추정이므로 지적 목록에 섞지 않는다.
        if first.extra.get("flags"):
            from .mistranslation import summarize as _flag_summary
            report["mistranslation_flags"] = [f.to_dict() for f in first.extra["flags"]]
            report["mistranslation_summary"] = _flag_summary(first.extra["flags"])

        # **회차는 인자다.** 전에는 `("2차", "3차")[:passes - 1]`을 여기와 GUI에 각각
        # 적어 두어 3차를 넘길 수 없었다.
        if args.passes > 1:
            from .revise import report as revision_report
            later = stage_revise(translated, profile, translator=translator,
                                 source={e.index: e.text for e in events},
                                 glossary=glossary, rounds=args.passes - 1,
                                 max_rounds=(args.max_passes - 1
                                             if args.max_passes > args.passes else 0),
                                 settle_at=args.settle_at,
                                 # **회차마다 남긴다.** 회차 사이를 견줄 수 있어야
                                 # 어느 회차에서 나빠졌는지 알 수 있다.
                                 on_round=((lambda label, role, evs, changed:
                                            work.save(f"03-revise-{label}", evs,
                                                      model=translator.model,
                                                      extra={"changed": changed,
                                                             "role": role}))
                                           if work else None),
                                 # 캐릭터 시트가 있으면 **정한 말투대로 쓰게** 한다.
                                 # 같은 시트가 T17 검사도 돌린다 — 정하고, 쓰고,
                                 # 검사하는 것이 한 자료다.
                                 cast=getattr(args, "_cast", None),
                                 target_lang=profile.get("language") or "ko",
                                 progress=say)
            translated = later.events
            print(f"  {revision_report(later.extra['revisions'], show=6)}")
            # **멈춘 이유를 남긴다.** "5차에서 멈췄다"만으로는 다 끝난 것인지 상한에
            # 걸린 것인지 알 수 없고, 상한에 걸린 것은 아직 덜 됐다는 뜻이다.
            report["revision_stopped_because"] = later.extra["stopped_because"]
            report["revision_rounds"] = later.extra["rounds"]
            print(f"  {later.extra['stopped_because']}", file=sys.stderr)
            for row in later.extra["rounds"]:
                stage_revisions = [r for r in later.extra["revisions"]
                                   if r.stage == row["stage"]]
                report[f"revisions_{row['stage']}"] = [
                    {"event_index": r.index, "before": r.before, "after": r.after}
                    for r in stage_revisions]

        # **윤문이 끝난 뒤에 잰다.** 2차·3차가 글자를 줄이며 뜻을 깎을 수 있어서,
        # 1차만 검증하면 그 유실을 못 잡는다.
        if getattr(args, "backtranslate", False):
            from .pipeline import stage_backtranslate
            checked = stage_backtranslate(
                translated, profile, translator=translator,
                source={e.index: e.text for e in events},
                language=args.lang if args.lang != "ko" else "en",
                worst=args.backtranslate_worst, progress=say)
            report["backtranslation"] = {
                "summary": checked.extra["summary"],
                "worst": [d.to_dict() for d in checked.extra["worst"]],
            }

        if work:
            report["work_dir"] = str(work.root)
            report["work_steps"] = work.steps()

        out_path = args.out or path.with_suffix(".ko.srt")
        write_srt(translated, out_path)
        report["translated_file"] = str(out_path)
        # 번역본은 타임코드를 그대로 물려받는다. 그것을 확인해 둔다.
        problem = _assert_timecodes_unchanged(
            _timecodes_of(events), _timecodes_of(translated), path)
        if problem:
            report["lock_violation"] = problem

    if args.fix:
        # 교정은 이미 `correct_and_check`가 끝냈다(한국어 -> 규정 -> 검사). 여기서는
        # 쓰기만 한다 — 두 번 고치면 검사가 설명한 자막과 파일이 달라진다.
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
        report["applied_fixes"] = result.extra["applied"]
        report["auto_but_unfixable"] = result.extra["unfixable"]
        # 자동으로 고친 위반은 검사에서 사라진다. 어느 줄을 어떻게 고쳤는지는
        # 여기에 남는다 — 규칙 이름만 있으면 되짚을 수 없다.
        report["text_changes"] = result.extra["edits"]
        report["korean_changed"] = result.extra["korean_changed"]

    return report


def _add_knp(glossary, args, near) -> None:
    """작업자가 만든 KNP 시트를 자동으로 먹인다.

    **이미 있는 것을 다시 만들게 하지 않는다.** 용어집을 따로 입력하라고 하면
    아무도 안 쓴다. 옆에 있으면 그냥 쓴다.
    """
    if getattr(args, "no_knp", False) or not near:
        return
    from .knp import find_for

    found = find_for(near)
    if not found:
        return
    added = glossary.merge_knp(found)
    if added:
        print(f"KNP 시트에서 용어 {added}개를 가져왔습니다: {found.name}")


def _terms_mode(args, ap) -> int:
    """용어를 뽑아 조사한다. **번역이 아니라 조사를 대신한다.**"""
    from .terms import extract, research, summarize, to_tsv

    files = collect_files(args.targets)
    if not files:
        ap.error("자막 파일이 필요합니다")

    texts: list[str] = []
    for path in files:
        texts.extend(e.text for e in parse(path))
    terms = extract(texts, min_count=1)
    print(f"용어 후보 {len(terms)}개")

    lookup = None
    if args.korean:
        try:
            backend_root = _corrector_root(args)
            lookup = _loanword_lookup(backend_root)
        except CorrectorUnavailable as exc:
            print(f"규범 용례 조회를 건너뜁니다: {exc}", file=sys.stderr)

    glossary = {}
    from .knp import find_for
    knp = find_for(files[0])
    if knp and not args.no_knp:
        from .knp import read_terms
        glossary = read_terms(knp)
        if glossary:
            print(f"KNP에서 이미 정한 용어 {len(glossary)}개를 씁니다: {knp.name}")

    if args.web:
        print("규범 용례에 없는 것은 위키백과에서도 찾습니다 — **낱말만 나갑니다**")
    research(terms, lookup=lookup, glossary=glossary, web=args.web,
             progress=lambda m: print(f"    {m}", file=sys.stderr))

    if not args.no_explain:
        from .terms import explain
        from .translate import TranslatorUnavailable, make_translator
        try:
            translator = make_translator(args.translate_model)
        except TranslatorUnavailable as exc:
            print(f"용어 설명을 건너뜁니다: {exc}", file=sys.stderr)
        else:
            print("각 용어가 무엇인지 로컬 모델에게 묻습니다(밖으로 나가지 않습니다)")
            explain(terms, translator,
                    progress=lambda m: print(f"    {m}", file=sys.stderr))

    stats = summarize(terms)
    print(f"근거 있는 표기 {stats['confirmed']}개 / 확인 필요 {stats['unknown']}개")

    out = args.out or files[0].with_suffix(".terms.tsv")
    out.write_text(to_tsv(terms), encoding="utf-8-sig")
    print(f"용어표를 저장했습니다: {out}")
    print("  엑셀에서 열어 KNP 시트에 붙여 넣으세요. 빈칸은 사람이 채웁니다.")
    return 0


def _corrector_root(args):
    """교정기 경로. 사전 조회는 거기 붙어 있다."""
    import os
    root = getattr(args, "ksc_path", None) or os.environ.get("KSC_PATH")
    if not root:
        raise CorrectorUnavailable("교정기 경로를 모릅니다(--ksc-path 또는 KSC_PATH)")
    return Path(root)


def _loanword_lookup(root: Path):
    """국립국어원 외래어 표기 용례 조회를 빌려 온다."""
    from .korean import _load_corrector_env

    if not (root / "subtitle_corrector").is_dir():
        raise CorrectorUnavailable(f"교정기가 없습니다: {root}")
    _load_corrector_env(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from subtitle_corrector.dictionary.terms import lookup_by_source
    except ImportError as exc:
        raise CorrectorUnavailable(f"사전을 불러오지 못했습니다: {exc}") from exc
    return lookup_by_source


def _characters_mode(args, ap) -> int:
    """캐릭터 분석 문서를 만든다. **KNP 시트와 다른 문서다.**

    KNP는 고유명사 표기를 통일하고(`--terms`), 이것은 말투와 인물 관계를 통일한다.
    하나의 작품을 여러 작업자가 나누어 하기 때문에 필요하다 — 시트가 없으면 인물마다
    말투가 작업자별로 갈린다.
    """
    from . import characters

    files = collect_files(args.targets)
    if not files:
        ap.error("자막 파일을 주세요")

    events = []
    for path in files:
        events += parse(path)
    if not events:
        print("자막 이벤트를 읽지 못했습니다.", file=sys.stderr)
        return 2

    people, counts = characters.extract(events)
    if not people:
        # 화자 표시가 없으면 인물을 가릴 수 없다. 없는 것을 지어내지 않는다.
        print("화자 표시([이름])가 없어 인물을 가리지 못했습니다. "
              "SDH 자막이나 화자명이 붙은 대본이 필요합니다.", file=sys.stderr)
        return 1

    print(f"인물 {counts['total']}명 · 화자 표시가 붙은 자막 {counts['tagged_events']}개")
    if counts["untagged_events"]:
        print(f"  화자를 모르는 자막 {counts['untagged_events']}개는 집계에서 뺐습니다 "
              f"— 앞 화자에게 이어 붙이면 말투가 틀린 인물에게 쌓입니다.")

    research_info = None
    if args.wiki:
        # **기본은 꺼져 있다.** `--wiki`를 준 것이 곧 밖으로 조회하겠다는 뜻이다.
        print(f"밖에서 조사합니다({args.wiki}) — 작품 제목과 인물 이름만 나갑니다. "
              f"대사는 나가지 않습니다.")
        research_info = characters.research(
            people, args.wiki, args.work_title, limit=args.characters_limit,
            progress=lambda m: print(f"    {m}", file=sys.stderr))

    base = files[0]
    tsv_path = args.out or base.with_suffix(".characters.tsv")
    md_path = tsv_path.with_suffix(".md")
    # 표는 KNP처럼 붙여 쓰고, 문서는 사진을 붙일 수 있어야 해서 둘 다 낸다.
    tsv_path.write_text(characters.to_tsv(people), encoding="utf-8-sig")
    md_path.write_text(characters.to_markdown(people, counts, args.work_title or base.stem),
                       encoding="utf-8")

    stats = characters.summarize(people)
    print(f"표: {tsv_path}")
    print(f"문서: {md_path}")
    print(f"  조사된 인물 {stats['researched']}/{stats['total']}명 · "
          f"관계가 빈 인물 {stats['no_relation']}명 · "
          f"말투를 재지 못한 인물 {stats['tone_unknown']}명")
    if research_info:
        # 무엇을 내보냈는지 숨기지 않는다.
        print(f"  밖으로 보낸 것 {len(research_info['sent'])}건: "
              + ", ".join(research_info["sent"][:8])
              + (" …" if len(research_info["sent"]) > 8 else ""))
    print("  관계는 자막이 증명하지 못합니다. 표의 '관계' 칸은 사람이 채웁니다 — "
          "그것이 채워지면 T17(같은 관계에서 존댓말·반말 혼용) 검사가 성립합니다.")
    return 0


def _bookmarks_mode(args, ap) -> int:
    """강사 첨삭을 데이터로. **전문가가 짚은 실패 사례 목록**이다."""
    from .bookmarks import collect, read, summarize

    target = args.bookmarks
    if not target.exists():
        ap.error(f"찾지 못했습니다: {target}")
    notes = collect(target) if target.is_dir() else read(target)
    if not notes:
        print("북마크를 찾지 못했습니다.")
        return 1

    stats = summarize(notes)
    labels = {"timecode": "타임코드", "translation": "번역", "notation": "표기",
              "other": "기타"}
    print(f"첨삭 {stats['total']}건 (자막과 짝지음 {stats['with_cue']}건)")
    for kind, count in sorted(stats["by_kind"].items(), key=lambda kv: -kv[1]):
        print(f"  {labels.get(kind, kind):8} {count:3}건")

    for kind in ("timecode", "notation", "translation", "other"):
        found = [n for n in notes if n.kind == kind]
        if not found:
            continue
        print()
        print(f"[{labels.get(kind, kind)}]")
        for note in found:
            first = note.text.splitlines()[0]
            cue = f"  | {note.cue.text.replace(chr(10), ' / ')[:30]}" if note.cue else ""
            print(f"  {note.source[:18]:18} #{note.index:>3}  {first[:58]}{cue}")

    if args.eval_json:
        import json as _json
        args.eval_json.write_text(
            "\n".join(_json.dumps(n.to_dict(), ensure_ascii=False) for n in notes),
            encoding="utf-8")
        print(f"\n첨삭을 남겼습니다: {args.eval_json}")
    return 0


def _evaluate_mode(args, ap) -> int:
    """우리 자막 vs 정답 자막. **고칠 값을 읽기 위한 자리다.**"""
    from .evaluate import compare, report, save

    files = collect_files(args.targets)
    if len(files) != 1:
        ap.error("--against는 우리 자막 파일 하나와 함께 씁니다")
    if not args.against.is_file():
        ap.error(f"정답 자막을 찾지 못했습니다: {args.against}")

    ours, truth = parse(files[0]), parse(args.against)
    if not ours or not truth:
        print("자막을 읽지 못했습니다.", file=sys.stderr)
        return 1

    fps = args.fps
    if args.video and args.video.is_file():
        from .media import MediaToolUnavailable, probe
        try:
            fps = probe(args.video).fps or fps
        except MediaToolUnavailable:
            pass

    similarity_fn = None
    if args.semantic:
        from .embed import EmbeddingUnavailable, OllamaEmbedder, build_similarity_fn
        try:
            embedder = OllamaEmbedder()
            all_text = [e.text for e in ours] + [e.text for e in truth]
            print(f"임베딩으로 유사도를 잽니다 — 문장 {len(set(all_text))}개(중복 제외)")
            similarity_fn = build_similarity_fn(all_text, embedder)
        except EmbeddingUnavailable as exc:
            print(f"[오류] {exc}")
            return 2

    comparison = compare(ours, truth, similarity_fn=similarity_fn)
    print(f"우리 {files[0].name}  ↔  정답 {args.against.name}   ({fps:.3f}fps)")
    print()
    print(report(comparison, fps))

    if args.eval_json:
        save(comparison, args.eval_json, fps, note=f"{files[0].name} vs {args.against.name}")
        print(f"\n대조 결과를 남겼습니다: {args.eval_json}")
    return 0


def _ocr_scan_mode(args, ap) -> int:
    """영상에서 화면 캡션(그래픽 자막)을 읽어 본다. **보고용이다.**

    `detect_bottom_text()`는 글자가 있는지만 짐작하고, 이 모드가 실제로 읽는다.
    화면 글자 검출은 규칙4의 "추정"이라 여기서 만든 목록을 자막 Event로 바꾸거나
    자동 반영하지 않는다 — 1단계(추출+인식)까지만 한다(`docs/BACKLOG.md` 참고).
    """
    from .media import MediaToolUnavailable
    from .ocr import OcrUnavailable, detect_onscreen_captions

    if not args.video:
        ap.error("--ocr-scan에는 --video가 필요합니다")
    if not args.video.is_file():
        ap.error(f"영상을 찾지 못했습니다: {args.video}")

    try:
        captions = detect_onscreen_captions(
            args.video, lang=args.ocr_lang, sample_fps=args.ocr_sample_fps,
            min_confidence=args.ocr_min_confidence,
            min_similarity=args.ocr_min_similarity,
            max_duration_ms=args.ocr_max_duration, full_scan=not args.ocr_fast)
    except (MediaToolUnavailable, OcrUnavailable) as exc:
        print(f"[오류] {exc}")
        return 2

    if not captions:
        print("화면 캡션을 찾지 못했습니다.")
        return 0

    print(f"화면 캡션 후보 {len(captions)}개 (보고용 — 자동 반영되지 않습니다)")
    for c in captions:
        text = c.text.replace("\n", " / ")
        print(f"  {c.start_ms:>8}–{c.end_ms:<8}ms  ({c.confidence:.2f})  {text}")

    if args.ocr_json:
        import json as _json
        args.ocr_json.write_text(
            _json.dumps([{"start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text,
                          "confidence": c.confidence, "frame_count": c.frame_count}
                         for c in captions], ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"\nJSON으로 저장했습니다: {args.ocr_json}")
    return 0


def _sfx_scan_mode(args, ap) -> int:
    """대사 없는 구간에 무슨 소리가 나는지 오디오 분류 모델로 짐작해 본다.

    **보고용이다.** `checker/sfx.py` 독스트링 참고 — 자막 Event로 만들거나
    자동 반영하지 않는다. 1단계(짐작만)까지만 한다.
    """
    from .media import MediaToolUnavailable, find_speech, probe
    from .sfx import SfxUnavailable, detect_sound_events

    if not args.video:
        ap.error("--sfx-scan에는 --video가 필요합니다")
    if not args.video.is_file():
        ap.error(f"영상을 찾지 못했습니다: {args.video}")

    try:
        media = probe(args.video)
        speech, how = find_speech(args.video, duration_ms=media.duration_ms, progress=print)
        print(f"말소리 구간 {len(speech)}개 ({'모델' if how == 'vad' else '음량'})")
        events = detect_sound_events(args.video, speech, media.duration_ms,
                                     min_gap_ms=args.sfx_min_gap,
                                     min_confidence=args.sfx_min_confidence,
                                     progress=print)
    except (MediaToolUnavailable, SfxUnavailable) as exc:
        print(f"[오류] {exc}")
        return 2

    if not events:
        print("소리 후보를 찾지 못했습니다.")
        return 0

    print(f"\n소리 후보 {len(events)}개 (보고용 — 자동 반영되지 않습니다,"
          " 화면을 보고 확인해야 합니다)")
    for e in events:
        candidate = e.candidate or "(매핑 없음 — 라벨만 참고)"
        print(f"  {e.start_ms:>8}–{e.end_ms:<8}ms  ({e.confidence:.2f})  "
              f"{e.label:<28}  {candidate}")
    return 0


def _ocr_hardsub_mode(args, ap) -> int:
    """하드섭(화면 전체에 자막이 타 있는 영상)을 카드 단위 초안 srt로 뽑는다.

    **정답지가 아니다.** `tools/corpus_build.py`와 같은 원칙 — OCR은 타임코드도
    글자도 근사값이다. 임베디드 자막 트랙이 없어 `corpus_build.py`로 못 뽑을
    때만 쓴다. 사람이 영상과 대조해 고친 뒤에야 `학습한 TC 및 자막 모음/`에
    들어간다(`.claude/skills/정답지-학습/SKILL.md` 참고) — 여기서 만든 파일을
    그대로 옮기지 않는다.
    """
    from .media import MediaToolUnavailable
    from .ocr import OcrUnavailable, captions_to_draft_srt_events, detect_onscreen_captions
    from .writers import to_srt, write_srt

    if not args.video:
        ap.error("--ocr-hardsub에는 --video가 필요합니다")
    if not args.video.is_file():
        ap.error(f"영상을 찾지 못했습니다: {args.video}")

    # 대사 자막은 항상 화면 아래 중앙에 뜬다 — 전체를 읽으면 좌상단 작품명
    # 워터마크·배경 간판 글자까지 섞인다(실측, 2026-08-31). 기본 0.25.
    band = args.ocr_band if args.ocr_band is not None else 0.25
    try:
        captions = detect_onscreen_captions(
            args.video, lang=args.ocr_lang, sample_fps=args.ocr_sample_fps,
            min_confidence=args.ocr_min_confidence,
            min_similarity=args.ocr_min_similarity,
            max_duration_ms=args.ocr_max_duration, full_scan=not args.ocr_fast,
            band=band)
    except (MediaToolUnavailable, OcrUnavailable) as exc:
        print(f"[오류] {exc}")
        return 2

    if not captions:
        print("화면에서 자막을 찾지 못했습니다.")
        return 1

    events, notes = captions_to_draft_srt_events(captions)
    out = args.out or args.video.with_suffix(".ocr-draft.srt")
    write_srt(events, out)
    print(f"OCR 초안 {len(events)}개를 저장했습니다: {out}")
    print("이 파일은 정답지가 아닙니다 — 영상과 대조해 확인·수정한 뒤에만 "
          "학습 자료로 씁니다(정답지-학습 스킬 참고).")

    if notes:
        from .model import Event

        by_index = dict(notes)
        notes_path = out.with_suffix(".notes.srt")
        notes_path.write_text(
            to_srt([Event(ev.index, ev.start_ms, ev.end_ms, by_index.get(ev.index, "·"))
                   for ev in events]),
            encoding="utf-8")
        print(f"신뢰도 낮아 봐야 할 자리 {len(notes)}곳: {notes_path}")
    return 0


def _generate_mode(args, ap) -> int:
    """영상 -> 자막 초안. 검사 경로와 섞지 않는다 — 입력도 출력도 다르다."""
    from .generate import generate, notes_srt
    from .media import MediaToolUnavailable
    from .diarize import DiarizationUnavailable

    if not args.video:
        ap.error("--generate에는 --video가 필요합니다")
    if not args.video.is_file():
        ap.error(f"영상을 찾지 못했습니다: {args.video}")
    if args.ocr and not args.fn_marker:
        # whisper 전사(몇 분~몇십 분)를 다 돌리고 나서야 마커가 없다고 알리면
        # 낭비다 — 여기서 미리 막는다(--lock-timecodes 클래시 검사와 같은 자리).
        ap.error("--ocr에는 --fn-marker가 필요합니다(화면자막 표식이 정해지지 "
                 "않으면 만든 캡션을 검사기가 못 알아봅니다)")
    if args.sfx and args.lang != "ko":
        # AUDIOSET_TO_CANDIDATE(checker/sfx.py)는 한국어 문구만 담고 있다 —
        # 다른 언어는 자료가 없다(규칙9, 지어내지 않는다). 이것도 whisper를
        # 다 돌리고 나서 막으면 낭비라 여기서 미리 확인한다.
        ap.error("--sfx는 -l ko(한국어 SDH)에서만 됩니다 — 소리 후보 문구가 "
                 "한국어뿐입니다")

    from .media import list_subtitle_streams
    existing_subs = list_subtitle_streams(args.video)
    if existing_subs:
        desc = ", ".join(
            f"#{s['index']}({s['language'] or '?'}"
            f"{'·forced' if s['forced'] else ''}{'·' + s['title'] if s['title'] else ''})"
            for s in existing_subs
        )
        print(f"경고: 이 영상에 자막 스트림이 이미 {len(existing_subs)}개 있습니다: {desc}",
              file=sys.stderr)
        print("      이미 있는 자막이 정답일 수 있다 — whisper로 새로 만들기 전에"
              " `정답지-학습` 스킬로 먼저 추출해 확인하는 것을 권합니다.", file=sys.stderr)

    profile = _genre.apply(
        (load_profile_file(args.profile) if args.profile
         else load_profile(args.platform, args.lang, args.kind)),
        getattr(args, "genre", None))
    print(f"프로파일: {profile.get('platform')} {profile.get('language')} "
          f"{profile.get('kind')}")

    if args.dry_run:
        from . import preflight
        checks = preflight.run(args.video, profile, translate=args.translate,
                               diarize=args.diarize, speech_method=args.speech,
                               translate_model=args.translate_model,
                               whisper_model=args.whisper_model,
                               check_context=args.check_context)
        print(preflight.report(checks))
        return 1 if any(not c.ok for c in checks) else 0

    translator = glossary = None
    if args.translate:
        from .translate import Glossary, TranslatorUnavailable, make_translator
        try:
            translator = make_translator(args.translate_model)
        except TranslatorUnavailable as exc:
            print(f"[오류] {exc}")
            return 2
        glossary = Glossary.from_profile(profile)
        if args.glossary:
            glossary.merge_file(args.glossary)
        _add_knp(glossary, args, args.video)
        if glossary.terms:
            print(f"표기 통일표 {len(glossary.terms)}개를 적용합니다")

    # **문맥 검사는 번역과 별개다.** --translate 없이 SDH만 만들 때도 켤 수
    # 있으므로, 번역기가 이미 있으면 그것을 그대로 쓰고 없으면 따로 만든다.
    context_checker = translator
    if args.check_context and context_checker is None:
        from .translate import TranslatorUnavailable, make_translator
        try:
            context_checker = make_translator(args.translate_model)
        except TranslatorUnavailable as exc:
            print(f"[오류] {exc}")
            return 2

    # 번역기·문맥 검사기 중 이미 만든 것이 있으면 그대로 쓴다 — Ollama 접속을
    # 세 번 따로 열 이유가 없다.
    foreign_translator = translator or context_checker
    if args.translate_foreign and foreign_translator is None:
        from .translate import TranslatorUnavailable, make_translator
        try:
            foreign_translator = make_translator(args.translate_model)
        except TranslatorUnavailable as exc:
            print(f"[오류] {exc}")
            return 2

    out = args.out or args.video.with_suffix(".draft.srt")
    try:
        draft = generate(args.video, profile, script=args.script,
                         language=args.whisper_lang, model=args.whisper_model,
                         fps=None, use_gpu=not args.cpu, translator=translator,
                         speech_method=args.speech, diarize=args.diarize,
                         glossary=glossary,
                         keep_source=out.with_suffix(".source.srt") if translator else None,
                         passes=args.passes, max_passes=args.max_passes,
                         settle_at=args.settle_at, cast=getattr(args, "_cast", None),
                         context_checker=context_checker if args.check_context else None,
                         foreign_dialogue_translator=(
                             foreign_translator if args.translate_foreign else None),
                         progress=print)
    except DiarizationUnavailable as exc:
        print(f"[오류] {exc}")
        return 2
    except MediaToolUnavailable as exc:
        print(f"[오류] {exc}")
        return 2

    if not draft.events:
        print("말소리를 찾지 못했습니다.")
        return 1

    from .position import JobRules
    rules = JobRules.from_profile(profile, {
        "marker": args.fn_marker, "policy": args.collision,
        "move_to": args.collision_move_to,
    })

    if args.ocr:
        # **--ocr-scan(독립 진단)과 다르다.** 여기서는 실제로 최종 자막에
        # 합친다 — 마커 없이 합치면 방금 만든 캡션을 `is_forced_narrative()`가
        # 못 알아보고 겹침 검사(C10 등)도 못 잡는다. `--fn-marker` 자체는
        # 함수 맨 위에서 이미 확인했다(whisper를 다 돌리고 나서 막으면 낭비다).
        from .ocr import OcrUnavailable, captions_to_events, detect_onscreen_captions, merge_captions
        try:
            captions = detect_onscreen_captions(
                args.video, lang=args.ocr_lang, sample_fps=args.ocr_sample_fps,
                min_confidence=args.ocr_min_confidence,
                min_similarity=args.ocr_min_similarity,
                max_duration_ms=args.ocr_max_duration, full_scan=not args.ocr_fast)
        except (MediaToolUnavailable, OcrUnavailable) as exc:
            print(f"[오류] {exc}")
            return 2

        if not captions:
            print("화면 캡션을 찾지 못했습니다.")
        else:
            caption_events = captions_to_events(captions, start_index=len(draft.events) + 1)
            confidences = {ev.index: c.confidence for ev, c in zip(caption_events, captions)}
            if translator:
                from .translate import to_events, translate_events
                target_lang = profile.get("language") or "ko"
                cues = translate_events(caption_events, translator, glossary,
                                        target_lang=target_lang, progress=print)
                caption_events = to_events(cues, caption_events)
            draft.events, draft.notes = merge_captions(
                draft.events, draft.notes, caption_events, confidences, rules.marker)
            print(f"화면 캡션 {len(captions)}개를 자막에 얹었습니다")

    if args.sfx:
        # **--sfx-scan(독립 진단)과 다르다.** 여기서는 실제로 최종 자막에
        # 합친다. -l ko 확인은 함수 맨 위에서 이미 했다(whisper를 다 돌리고
        # 나서 막으면 낭비다). VAD는 `generate()` 안에서 이미 한 번 돌았지만
        # 그 결과를 밖으로 안 내보내(Draft에 없음) 여기서 다시 돈다 —
        # `--ocr`도 같은 이유로 독립적으로 돈다.
        from .media import find_speech, probe
        from .sfx import SfxUnavailable, detect_sound_events, merge_sound_events, \
            sound_events_to_draft_events
        try:
            media = probe(args.video)
            speech, _how = find_speech(args.video, duration_ms=media.duration_ms,
                                       progress=print)
            sound_events = detect_sound_events(
                args.video, speech, media.duration_ms,
                min_gap_ms=args.sfx_min_gap, min_confidence=args.sfx_min_confidence,
                progress=print)
        except (MediaToolUnavailable, SfxUnavailable) as exc:
            print(f"[오류] {exc}")
            return 2

        sfx_events = sound_events_to_draft_events(sound_events, start_index=len(draft.events) + 1)
        if not sfx_events:
            print("소리 후보를 찾지 못했습니다(매핑되는 것이 없었을 수 있습니다).")
        else:
            draft.events, draft.notes = merge_sound_events(
                draft.events, draft.notes, sfx_events)
            print(f"소리 후보 {len(sfx_events)}개를 자막에 얹었습니다"
                  " — 전부 확인 필요로 표시됩니다")

    # **여기서 끝내지 않는다.** 예전에는 초안만 쓰고 검사·교정은 사용자가 다시
    # 돌려야 했는데, 그러면 버튼 이름만 보고는 어디까지 된 것인지 알 수 없다
    # (사용자 지적). 만들었으면 검사까지 하고, 고칠 수 있는 것은 고쳐서 낸다.
    events = draft.events
    if not args.no_check:
        from .fixes import apply_fixes

        # 단계 순서를 여기서 정하지 않는다 — `pipeline`이 정한다. 그리고 전에는
        # 한국어 위반(`ko_violations`)을 받아 놓고 쓰지 않아 **화면에 한 건도 뜨지
        # 않았다.** 이제 규정 위반과 한 목록으로 합쳐 나온다.
        from .pipeline import CorrectOptions, correct_and_check

        result = correct_and_check(
            events, profile,
            CorrectOptions(
                korean=bool(args.korean and args.lang == "ko"),
                corrector_path=args.ksc_path,
                spacing_mode=args.spacing,
                apply_fixes=True,
                children=args.children,
                job_rules=rules,
            ),
            progress=lambda m: print(m),
        )
        for note in result.notes:
            print(note, file=sys.stderr)
        events = result.events
        applied = result.extra["applied"] or []
        unfixable = result.extra["unfixable"] or []
        if applied:
            print(f"규정 자동 교정: {', '.join(applied)}")
        left = result.violations
        print(f"검사 결과 남은 지적 {len(left)}건"
              + (" — 사람이 봐야 하는 것들입니다" if left else ""))
        if left:
            counts: dict = {}
            for v in left:
                counts[(v["rule_id"], v["message"])] = counts.get(
                    (v["rule_id"], v["message"]), 0) + 1
            for (rule_id, message), n in sorted(counts.items(), key=lambda kv: -kv[1])[:6]:
                print(f"    {n:>3}건  {rule_id}  {message}")
        if unfixable:
            print("  자동 표시지만 기계가 못 고치는 것: " + ", ".join(unfixable))
        unimplemented = result.extra["report"].get("unimplemented_checks") or []
        if unimplemented:
            # --check 모드는 이미 이 줄을 낸다(193행). --generate만 빠져 있었다 —
            # 검사하지 않은 것을 조용히 "통과"로 보이게 하면 규칙 9를 어긴다.
            print(f"  미구현 검사 {len(unimplemented)}건: " + ", ".join(unimplemented))

    if draft.revisions:
        from .revise import report as revision_report
        print(f"\n{revision_report(draft.revisions, show=6)}")
        if draft.stats.get("revision_stopped_because"):
            print(f"  {draft.stats['revision_stopped_because']}")

    write_srt(events, out)
    print(f"\n자막을 저장했습니다: {out}  (자막 {len(events)}개)")

    if draft.notes:
        notes_path = out.with_suffix(".notes.srt")
        notes_path.write_text(notes_srt(draft), encoding="utf-8")
        print(f"봐야 할 자리 {len(draft.notes)}곳: {notes_path}")
        print("  SE에서 초안을 연 뒤 [파일 - 원본 자막 열기]로 이 파일을 얹으면 "
              "나란히 보입니다.")

    print("\n초안입니다. 사람이 보고 고치는 것을 전제로 만들었습니다.")
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
    ap.add_argument("--genre", choices=["documentary", "drama", "variety"],
                    help="장르를 플랫폼 프로파일 위에 얹는다. 호칭 규칙과 권장 표시 "
                         "시간이 달라진다(작업자 자료 590·658·659행). "
                         "멜로는 drama, 느와르도 drama를 쓴다 — 거친 표현은 장르가 "
                         "아니라 캐릭터가 정하고 검열 금지는 이미 플랫폼 규정이다")
    ap.add_argument("--video", type=Path,
                    help="영상 파일. 프레임레이트를 자동으로 읽고 --spot에 쓴다(ffmpeg 필요)")
    ap.add_argument("--spot", action="store_true",
                    help="말소리 구간과 견줘 인점·아웃점을 제안한다(자동 교정 아님)")
    ap.add_argument("--ocr-scan", action="store_true",
                    help="화면에 타 있는 캡션(그래픽 자막)을 EasyOCR로 읽어 목록만 "
                         "낸다(--video 필요). **보고용이다** — 화면 글자 검출은 "
                         "추정이라(규칙4) 자막 Event로 만들거나 자동 반영하지 않는다. "
                         "인식은 격리 venv(.venv-ocr)에서 돈다(없으면 오류, 조용히 "
                         "건너뛰지 않음)")
    ap.add_argument("--ocr-lang", default="en",
                    help="캡션 언어(easyocr 언어 코드, 기본 en)")
    ap.add_argument("--ocr-sample-fps", type=float, default=2.0,
                    help="초당 몇 프레임을 뽑아 인식할지(기본 2.0)")
    ap.add_argument("--ocr-fast", action="store_true",
                    help="detect_bottom_text()로 화면 아래 25%%만 먼저 추려 그 "
                         "구간만 인식한다(빠르다). **기본은 이게 아니라 전체 "
                         "프레임을 다 훑는 쪽이다** — 실측(2026-08-30, 예능A "
                         "시즌2 19회)에서 이 선필터가 캡션을 0개 찾았다(캡션이 "
                         "화면 아래가 아니라 인물 옆에 떴다). 위치가 항상 화면 "
                         "아래인 걸 아는 자료에서만 쓴다")
    ap.add_argument("--ocr-min-confidence", type=float, default=0.4,
                    help="이 미만 신뢰도의 인식 결과는 버린다(기본 0.4)")
    ap.add_argument("--ocr-min-similarity", type=float, default=0.6,
                    help="인접 프레임 텍스트를 같은 캡션으로 볼 편집 유사도 "
                         "기준(0~1, 기본 0.6). 완전 일치를 요구하면 압축·모션 "
                         "블러로 흔들린 프레임이 매번 새 캡션으로 갈린다(실측)")
    ap.add_argument("--ocr-max-duration", type=int, default=None,
                    help="캡션 하나가 최대 이만큼(ms)까지만 이어 붙는다. 기본은 "
                         "상한 없음 — 이름표 캡션·워터마크류는 실제로 수십~수백초 "
                         "떠 있는다(실측, 2026-08-31: \"Sebastiam/Tomy/Scarlet\" "
                         "이름 캡션이 25초 넘게 그대로였다). 증거 없이 상한을 "
                         "두면 그런 정상 캡션을 인위적으로 쪼갠다 — 정말 필요할 "
                         "때만 켠다")
    ap.add_argument("--ocr-json", type=Path,
                    help="--ocr-scan 결과를 JSON으로도 남긴다")
    ap.add_argument("--ocr-hardsub", action="store_true",
                    help="화면 전체에 타 있는 자막(하드섭)을 OCR로 카드 단위 "
                         "초안(srt)으로 뽑는다(--video 필요). **정답지가 아니다** "
                         "— corpus_build.py와 같은 원칙, OCR은 타임코드도 글자도 "
                         "근사값이다. 영상과 대조해 사람이 고친 뒤에만 "
                         "학습한 TC 및 자막 모음/에 넣는다(정답지-학습 스킬)")
    ap.add_argument("--ocr-band", type=float, default=None,
                    help="화면 아래 이 비율만 잘라서 읽는다(0~1). --ocr-hardsub는 "
                         "기본 0.25 — 대사 자막은 항상 아래 중앙에 뜨는데 전체를 "
                         "읽으면 좌상단 작품명 워터마크·배경 간판 글자까지 섞인다"
                         "(실측). --ocr-scan/--ocr은 기본 None(전체 프레임) — "
                         "예능 화면 캡션은 위치가 안 정해져 있다")
    ap.add_argument("--sfx-scan", action="store_true",
                    help="대사 없는 구간마다 오디오 분류 모델(AudioSet)로 무슨 "
                         "소리인지 짐작해 목록만 낸다(--video 필요). **보고용이다** "
                         "— 소리 검출은 추정이라(규칙4) 자막 Event로 만들거나 "
                         "자동 반영하지 않는다. 분위기(따뜻한/슬픈 등)나 화면을 "
                         "봐야 아는 구체 동작은 못 짐작한다 — 수식어 없는 일반형"
                         "후보만 낸다(`checker/sfx.py` 참고)")
    ap.add_argument("--sfx-min-confidence", type=float, default=0.3,
                    help="이 미만 확신도의 소리 후보는 버린다(기본 0.3)")
    ap.add_argument("--sfx-min-gap", type=int, default=1000,
                    help="대사 없는 구간이 이 미만(ms)이면 짐작하지 않는다(기본 1000)")
    ap.add_argument("--sfx", action="store_true",
                    help="`--sfx-scan`처럼 소리 후보를 찾되, 실제로 최종 자막에 "
                         "얹는다(--video 필요, -l ko 전용 — 후보 문구가 한국어뿐). "
                         "얹은 자리는 예외 없이 확인 필요로 표시된다(checker/sfx.py "
                         "참고 — 신뢰도와 무관하게 전부 추정이다). "
                         "--sfx-min-confidence/--sfx-min-gap을 그대로 같이 쓴다")
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
    ap.add_argument("--terms", action="store_true",
                    help="작품에 나오는 고유명사·약어·용어를 뽑아 조사한다. "
                         "KNP 시트에 붙일 수 있는 표로 낸다")
    ap.add_argument("--no-explain", action="store_true",
                    help="용어 설명을 붙이지 않는다(기본은 로컬 모델로 한 줄 설명)")
    ap.add_argument("--web", action="store_true",
                    help="규범 용례에 없는 것을 위키백과에서도 찾는다. "
                         "**낱말만 보낸다** — 대사는 나가지 않는다. 기본은 끔")
    ap.add_argument("--no-work", action="store_true",
                    help="단계별 결과를 <자막이름>.work/에 남기지 않는다. 기본은 "
                         "남긴다 — 15분 걸린 번역이 3차에서 깨지면 처음부터 하게 되고, "
                         "그것이 실사용에서 가장 비쌌다")
    ap.add_argument("--backtranslate", action="store_true",
                    help="번역을 원어로 되돌려 원문과 견준다. 같은 언어끼리 견주므로 "
                         "낱말로 잴 수 있고, 어긋난 자리를 원문·번역·역번역 3단으로 "
                         "보여 준다. **한 회차 더 도는 비용이다.** 로컬 모델로만 돈다")
    ap.add_argument("--backtranslate-worst", type=int, default=20,
                    help="역번역 결과에서 점수 낮은 순으로 몇 개를 보일지(기본 20). "
                         "임계값을 두지 않는 이유는 몇 점 이하가 오역인지 실제 "
                         "작업물로 재야 알기 때문이다 — 판정이 아니라 순위다")
    ap.add_argument("--cast", type=Path,
                    help="캐릭터 시트(--characters로 만든 .characters.tsv). "
                         "'말투 지정' 칸을 채워 주면 T17(정한 말투를 벗어난 자리)이 "
                         "돈다. **주지 않으면 T17은 돌지 않는다** — 같은 인물이 "
                         "존댓말과 반말을 섞는 것은 상대가 다르면 정상이고, 자막에 "
                         "상대는 표시되지 않기 때문이다")
    ap.add_argument("--characters", action="store_true",
                    help="등장인물을 뽑아 캐릭터 분석 문서를 만든다. **KNP 시트와 다른 "
                         "문서다** — KNP는 고유명사 표기를, 이것은 말투와 인물 관계를 "
                         "통일한다. 하나의 작품을 여러 작업자가 나누어 하기 때문에 필요하다")
    ap.add_argument("--wiki",
                    help="캐릭터 조사에 쓸 위키(예: breakingbad 또는 전체 주소). "
                         "**주면 밖으로 조회한다** — 나가는 것은 작품 제목과 인물 "
                         "이름뿐이고 대사는 어떤 경우에도 나가지 않는다. 안 주면 "
                         "자막에서 알 수 있는 것만 채운다")
    ap.add_argument("--work-title", default="",
                    help="작품 제목. 위키 안에서 같은 이름이 여럿일 때 검색어에 붙는다")
    ap.add_argument("--characters-limit", type=int, default=0,
                    help="대사가 많은 인물부터 이만큼만 조사한다(기본: 전원). "
                         "단역은 위키에 문서가 없는 것이 보통이다")
    ap.add_argument("--bookmarks", type=Path,
                    help="SubtitleEdit 북마크(강사 첨삭)를 모아 갈래별로 낸다. "
                         "폴더를 주면 그 안의 것을 모두 읽는다")
    ap.add_argument("--against", type=Path,
                    help="정답 자막과 대조한다. 인점·아웃점이 어느 방향으로 얼마나 "
                         "어긋나는지 재서, 감이 아니라 값으로 고칠 수 있게 한다")
    ap.add_argument("--eval-json", type=Path,
                    help="대조 결과를 JSON으로 남긴다(정답 파일이 쌓이면 학습 자료가 된다)")
    ap.add_argument("--semantic", action="store_true",
                    help="--against의 짝짓기·유사도를 글자 겹침 대신 임베딩(bge-m3, "
                         "Ollama 필요)으로 잰다. 의역이라 글자는 안 겹쳐도 뜻이 같은 "
                         "자리를 잡는다(2026-08-27 예능A 15회에서 발견한 문제)")
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
    gen.add_argument("--speech", choices=["auto", "vad", "loudness"], default="auto",
                     help="말소리를 어떻게 찾을지. auto는 모델(VAD)을 먼저 쓰고 "
                          "없으면 음량으로 돌아간다")
    gen.add_argument("--diarize", action="store_true",
                     help="화자가 바뀌는 자리를 찾아 병합 때 넘지 않는다(pyannote.audio "
                          "필요, 없으면 오류 — 조용히 건너뛰지 않는다). 화자 '이름'은 "
                          "여전히 못 준다, 몇 번째 화자인지만 구분한다")
    gen.add_argument("--cpu", action="store_true",
                     help="GPU를 쓰지 않는다(느리다). 기본은 GPU")
    gen.add_argument("--no-check", action="store_true",
                     help="만들기만 하고 검사·교정은 건너뛴다. 기본은 만든 뒤 "
                          "검사까지 하고 고칠 수 있는 것을 고친다")
    gen.add_argument("--dry-run", action="store_true",
                     help="실행하지 않고 환경(ffmpeg·모델·Ollama·화자 분리·디스크 "
                          "공간)만 점검한다. 전사·번역은 몇 분~몇십 분 걸리므로 "
                          "환경 문제로 중간에 멈추는 것을 미리 잡는다. 번역·TC "
                          "로직 자체의 정확도는 이 점검으로 못 잡는다 — 그건 "
                          "실행해야 안다")
    gen.add_argument("--translate", action="store_true",
                     help="원어를 한국어 초벌로 옮긴다. 모델은 이 컴퓨터에서 돈다"
                          "(원고가 밖으로 나가지 않는다)")
    gen.add_argument("--translate-model",
                     help="번역에 쓸 로컬 모델(기본: exaone3.5:7.8b). "
                          "`ollama list`에 있는 이름")
    gen.add_argument("--check-context", action="store_true",
                     help="번역 전에 전사 원문이 앞뒤 맥락과 맞는지 로컬 모델로 "
                          "확인해 알린다(고치지 않는다, 규칙 4). whisper가 비슷한 "
                          "소리를 다른 말로 잘못 들었을 때 걸러낸다. --translate "
                          "없이 SDH만 만들 때도 켤 수 있다 — 그때는 --translate-model로 "
                          "쓸 모델을 고른다")
    gen.add_argument("--translate-foreign", action="store_true",
                     help="원어(대개 한국어) 사이에 섞인 외국어 대사를 로컬 모델로 "
                          "한국어로 옮기고 언어 표시([일본어] 등)를 붙인다(초안 — "
                          "옮긴 자리는 notes에 남는다, 고쳐서 확정하지 않는다). "
                          "화자 이름은 모르므로 지어내지 않는다(--script로 대본을 "
                          "주면 사람이 나중에 채운다). --translate-model로 쓸 모델을 "
                          "고른다")
    gen.add_argument("--passes", type=int, default=1,
                     help="번역을 몇 차까지 할지. 1차=빠른 초벌, 2차=용어·맥락 감수, "
                          "3차=말맛 윤문(작업자 자료의 단계 그대로)")
    gen.add_argument("--max-passes", type=int, default=0,
                     help="수렴을 볼 상한 회차. --passes보다 크게 주면 그 사이에서 "
                          "**고친 자막이 없어질 때까지** 돈다. 안 주면 --passes만큼만 "
                          "돈다. 모델은 미사여구를 영원히 만지므로 상한이 필요하다")
    gen.add_argument("--settle-at", type=int, default=0,
                     help="한 회차에서 고친 자막이 이 수 이하이면 멈춘다(기본 0)")
    gen.add_argument("--no-knp", action="store_true",
                     help="옆에 있는 KNP 시트를 쓰지 않는다(기본은 찾으면 쓴다)")
    gen.add_argument("--glossary", type=Path,
                     help="표기 통일표. `원어=한국어` 한 줄에 하나. "
                          "발주처가 주는 표를 그대로 쓴다")
    gen.add_argument("--ocr", action="store_true",
                     help="화면 캡션(그래픽 자막)도 EasyOCR로 읽어 대사 자막에 "
                          "얹는다. **--fn-marker가 반드시 있어야 한다** — 마커 "
                          "없이 합치면 방금 만든 캡션을 검사기가 못 알아본다. "
                          "--ocr-scan(독립 진단)과 다르다 — 이건 실제로 최종 "
                          "자막에 들어간다. --ocr-lang/--ocr-sample-fps 등"
                          "세부 조정 플래그를 그대로 같이 쓴다")
    args = ap.parse_args(argv)

    if args.generate:
        return _generate_mode(args, ap)

    if args.terms:
        return _terms_mode(args, ap)

    if args.characters:
        return _characters_mode(args, ap)

    if args.bookmarks:
        return _bookmarks_mode(args, ap)

    if args.against:
        return _evaluate_mode(args, ap)

    if args.ocr_scan:
        return _ocr_scan_mode(args, ap)

    if args.ocr_hardsub:
        return _ocr_hardsub_mode(args, ap)

    if args.sfx_scan:
        return _sfx_scan_mode(args, ap)

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
        # 장르는 **플랫폼 프로파일 위에 얹는다.** 자료가 장르로 타임코드 길이와
        # 호칭 규칙을 가르므로 프롬프트가 아니라 이 층에 있어야 검사기가 본다.
        profile = _genre.apply(profile, getattr(args, "genre", None))
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

    # 캐릭터 시트는 **한 번만 읽는다.** 파일마다 읽으면 같은 표를 몇 번씩 읽는다.
    args._cast = None
    if getattr(args, "cast", None):
        from . import characters as _characters
        try:
            people = _characters.read_tsv(args.cast)
        except OSError as exc:
            print(f"캐릭터 시트를 읽지 못했습니다: {exc}", file=sys.stderr)
            return 2
        args._cast = {p.name: p.declared_tone for p in people if p.declared_tone}
        # **채워지지 않았으면 그렇게 말한다.** 조용히 넘기면 T17이 돈 것처럼 보인다.
        if args._cast:
            print(f"캐릭터 시트: 말투를 정한 인물 {len(args._cast)}명 "
                  f"(전체 {len(people)}명)", file=sys.stderr)
        else:
            print(f"캐릭터 시트에 '말투 지정' 칸이 비어 있어 T17은 돌지 않습니다 "
                  f"(인물 {len(people)}명). 칸을 채우면 정한 말투를 벗어난 자리를 "
                  f"찾습니다.", file=sys.stderr)

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
