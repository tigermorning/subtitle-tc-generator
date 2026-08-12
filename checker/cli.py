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
        first = stage_translate(events, profile, translator=translator,
                                glossary=glossary, progress=say)
        translated = first.events
        report["translation_notes"] = first.extra["notes_by_index"]

        # **회차는 인자다.** 전에는 `("2차", "3차")[:passes - 1]`을 여기와 GUI에 각각
        # 적어 두어 3차를 넘길 수 없었다.
        if args.passes > 1:
            from .revise import report as revision_report
            later = stage_revise(translated, profile, translator=translator,
                                 source={e.index: e.text for e in events},
                                 glossary=glossary, rounds=args.passes - 1,
                                 progress=say)
            translated = later.events
            print(f"  {revision_report(later.extra['revisions'], show=6)}")
            for row in later.extra["rounds"]:
                stage_revisions = [r for r in later.extra["revisions"]
                                   if r.stage == row["stage"]]
                report[f"revisions_{row['stage']}"] = [
                    {"event_index": r.index, "before": r.before, "after": r.after}
                    for r in stage_revisions]

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

    comparison = compare(ours, truth)
    print(f"우리 {files[0].name}  ↔  정답 {args.against.name}   ({fps:.3f}fps)")
    print()
    print(report(comparison, fps))

    if args.eval_json:
        save(comparison, args.eval_json, fps, note=f"{files[0].name} vs {args.against.name}")
        print(f"\n대조 결과를 남겼습니다: {args.eval_json}")
    return 0


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

    out = args.out or args.video.with_suffix(".draft.srt")
    try:
        draft = generate(args.video, profile, script=args.script,
                         language=args.whisper_lang, model=args.whisper_model,
                         fps=None, use_gpu=not args.cpu, translator=translator,
                         speech_method=args.speech,
                         glossary=glossary,
                         keep_source=out.with_suffix(".source.srt") if translator else None,
                         progress=print)
    except MediaToolUnavailable as exc:
        print(f"[오류] {exc}")
        return 2

    if not draft.events:
        print("말소리를 찾지 못했습니다.")
        return 1

    # **여기서 끝내지 않는다.** 예전에는 초안만 쓰고 검사·교정은 사용자가 다시
    # 돌려야 했는데, 그러면 버튼 이름만 보고는 어디까지 된 것인지 알 수 없다
    # (사용자 지적). 만들었으면 검사까지 하고, 고칠 수 있는 것은 고쳐서 낸다.
    events = draft.events
    if not args.no_check:
        from .fixes import apply_fixes
        from .position import JobRules
        rules = JobRules.from_profile(profile, {
            "marker": args.fn_marker, "policy": args.collision,
            "move_to": args.collision_move_to,
        })

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
    ap.add_argument("--terms", action="store_true",
                    help="작품에 나오는 고유명사·약어·용어를 뽑아 조사한다. "
                         "KNP 시트에 붙일 수 있는 표로 낸다")
    ap.add_argument("--no-explain", action="store_true",
                    help="용어 설명을 붙이지 않는다(기본은 로컬 모델로 한 줄 설명)")
    ap.add_argument("--web", action="store_true",
                    help="규범 용례에 없는 것을 위키백과에서도 찾는다. "
                         "**낱말만 보낸다** — 대사는 나가지 않는다. 기본은 끔")
    ap.add_argument("--bookmarks", type=Path,
                    help="SubtitleEdit 북마크(강사 첨삭)를 모아 갈래별로 낸다. "
                         "폴더를 주면 그 안의 것을 모두 읽는다")
    ap.add_argument("--against", type=Path,
                    help="정답 자막과 대조한다. 인점·아웃점이 어느 방향으로 얼마나 "
                         "어긋나는지 재서, 감이 아니라 값으로 고칠 수 있게 한다")
    ap.add_argument("--eval-json", type=Path,
                    help="대조 결과를 JSON으로 남긴다(정답 파일이 쌓이면 학습 자료가 된다)")
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
    gen.add_argument("--cpu", action="store_true",
                     help="GPU를 쓰지 않는다(느리다). 기본은 GPU")
    gen.add_argument("--no-check", action="store_true",
                     help="만들기만 하고 검사·교정은 건너뛴다. 기본은 만든 뒤 "
                          "검사까지 하고 고칠 수 있는 것을 고친다")
    gen.add_argument("--translate", action="store_true",
                     help="원어를 한국어 초벌로 옮긴다. 모델은 이 컴퓨터에서 돈다"
                          "(원고가 밖으로 나가지 않는다)")
    gen.add_argument("--translate-model",
                     help="번역에 쓸 로컬 모델(기본: exaone3.5:7.8b). "
                          "`ollama list`에 있는 이름")
    gen.add_argument("--passes", type=int, default=1,
                     help="번역을 몇 차까지 할지. 1차=빠른 초벌, 2차=용어·맥락 감수, "
                          "3차=말맛 윤문(작업자 자료의 단계 그대로)")
    gen.add_argument("--no-knp", action="store_true",
                     help="옆에 있는 KNP 시트를 쓰지 않는다(기본은 찾으면 쓴다)")
    gen.add_argument("--glossary", type=Path,
                     help="표기 통일표. `원어=한국어` 한 줄에 하나. "
                          "발주처가 주는 표를 그대로 쓴다")
    args = ap.parse_args(argv)

    if args.generate:
        return _generate_mode(args, ap)

    if args.terms:
        return _terms_mode(args, ap)

    if args.bookmarks:
        return _bookmarks_mode(args, ap)

    if args.against:
        return _evaluate_mode(args, ap)

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
