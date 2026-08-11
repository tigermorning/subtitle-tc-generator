"""검사 실행부. CLI와 GUI가 **같은 경로**를 쓴다.

입구가 둘이라고 로직이 둘이면 언젠가 갈라진다 — 한쪽만 고친 버그가 다른 쪽에 남는다.
진행 상황은 콜백으로 밖에 넘긴다(CLI는 표준 오류로, GUI는 창에 뿌린다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import check_events
from .fixes import apply_fixes
from .korean import CorrectorUnavailable, load_backend, run_korean_pass
from .parsers import parse
from .writers import write_srt

SUBTITLE_SUFFIXES = (".srt", ".vtt")


@dataclass
class Options:
    children: bool = False
    fix: bool = False
    korean: bool = False
    ksc_path: str | None = None
    spacing: str = "principle"
    out: Path | None = None
    fps: float = 23.976        # 프레임 단위 규정(자막 간격 2프레임)을 환산할 때 쓴다


@dataclass
class RunResult:
    reports: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # 건너뛴 것 등, 숨기면 안 되는 사실


def collect_files(targets: list[Path]) -> tuple[list[Path], list[str]]:
    """파일과 폴더를 섞어 받아 자막 파일 목록으로 편다.

    폴더는 한 단계만 훑는다 — 회차 파일이 한 폴더에 모여 있는 작업 형태에 맞추고,
    교정 결과(`*.fixed.srt`)를 다시 집어 들지 않게 거른다.
    """
    files: list[Path] = []
    missing: list[str] = []
    for target in targets:
        target = Path(target)
        if target.is_dir():
            files.extend(
                p for p in sorted(target.iterdir())
                if p.suffix.lower() in SUBTITLE_SUFFIXES and not p.name.endswith(".fixed.srt")
            )
        elif target.is_file():
            files.append(target)
        else:
            missing.append(f"파일이 없습니다: {target}")
    return files, missing


def run_files(
    targets: list[Path],
    profile: dict,
    options: Options,
    progress: Callable[[str], None] | None = None,
) -> RunResult:
    say = progress or (lambda _msg: None)
    result = RunResult()

    files, missing = collect_files(targets)
    result.notes.extend(missing)
    if not files:
        result.notes.append("검사할 자막 파일이 없습니다.")
        return result

    backend = None
    if options.korean:
        say("한국어 교정기를 올리는 중입니다. 형태소 분석기 적재에 1~2분 걸립니다...")
        try:
            backend = load_backend(options.ksc_path)
            say("한국어 교정기 준비 완료.")
        except CorrectorUnavailable as e:
            # 못 돌렸다는 사실을 숨기지 않는다 — 통과로 보이면 안 된다.
            result.notes.append(f"한국어 교정 레인을 건너뜁니다: {e}")
            say(result.notes[-1])

    for n, path in enumerate(files, 1):
        say(f"[{n}/{len(files)}] {path.name} 검사 중...")
        events = parse(path)
        if not events:
            result.notes.append(f"자막을 읽지 못했습니다: {path.name}")
            continue

        report = check_events([e.__dict__ for e in events], profile,
                              children=options.children, fps=options.fps)
        report["file"] = str(path)

        ko_fixed = None
        if backend is not None:
            ko_fixed, ko_violations = run_korean_pass(
                events, backend, spacing_mode=options.spacing
            )
            report["violations"].extend(v.to_dict() for v in ko_violations)
            report["violations"].sort(key=lambda v: (v["event_index"], v["rule_id"]))

        if options.fix:
            fixed, applied, unfixable = apply_fixes(events, profile)
            if ko_fixed is not None:
                # 교정기 결과를 규정 자동 교정 위에 얹는다. 순서를 바꾸면 교정기가
                # 넣은 문장부호를 규정 교정이 다시 걷어내는 왕복이 생긴다.
                fixed, applied2, _ = apply_fixes(ko_fixed, profile)
                applied = sorted(set(applied) | set(applied2))
            out_path = options.out or path.with_suffix(".fixed.srt")
            write_srt(fixed, out_path)
            report["fixed_file"] = str(out_path)
            report["applied_fixes"] = applied
            report["auto_but_unfixable"] = unfixable

        result.reports.append(report)

    return result
