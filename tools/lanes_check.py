"""한 커밋이 성격이 다른 갈래를 동시에 벌이고 있는지 알린다(규칙 12).

## 왜 필요한가

규칙 12는 "갈래를 동시에 벌이지 않는다"고 정한다 — 코퍼스 추출·문서 정독·코드
수정처럼 성격이 다른 작업을 한꺼번에 벌이면 **어느 것도 끝까지 확인하지 못한 채**
다음 것으로 넘어가게 된다. 실제로 2026-08-31 세션에서 드라마B E02·E04를 근본원인만
확인하고 고치지 않은 채, 번역 나머지 언어도 얕게만 보고 새 기능(SFX)으로
넘어갔다(`CLAUDE.md` 규칙 13 안에 그 기록이 있다).

## 무엇을 보나

    코퍼스·학습   rules/learned/ · corpus/ · docs/corpus_status.yaml
    문서 정독     rules/sources/
    코드          checker/ · app/ · tools/ · tests/ · plugin/ · bin/
    규정          rules/<발주처>/ · rules/genre/  (문건 근거로만 고치는 층)

두 갈래 이상이 한 커밋에 함께 들어오면 말한다. `docs/`와 최상위 `*.md`는 갈래로
치지 않는다 — 어느 갈래든 기록은 함께 남기기 때문이다.

**덤으로 "최소 2편" 근거도 짚는다.** 학습값 파일의 `from.작품`이 한 편뿐인데
같은 커밋이 `checker/`를 고치고 있으면, 한 작품의 습관을 코드로 굳히는 중일 수
있다(규칙 12의 증거 기준 — 여러 작품에서 같은 방향이 나올 때만 코드를 고친다).

## 막지 않는다

**커밋 단위는 세션 단위가 아니다.** 한 갈래를 끝내고 다음으로 넘어가는 중에
정리 커밋이 겹칠 수도 있고, 코드 고침이 학습값 갱신을 정말로 함께 요구할 때도
있다. 그래서 이 검사는 종료 코드 0으로 끝난다 — 사람이 보고 판단한다(규칙 4와
같은 정신: 추정으로 막지 않는다).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LANES: dict[str, tuple[str, ...]] = {
    "코퍼스·학습": ("rules/learned/", "corpus/", "docs/corpus_status.yaml",
                "학습한 TC 및 자막 모음/"),
    "문서 정독": ("rules/sources/",),
    "규정": ("rules/genre/", "rules/netflix/", "rules/disney/", "rules/coupang/",
           "rules/lexicon/"),
    "코드": ("checker/", "app/", "tools/", "tests/", "plugin/", "bin/", "examples/"),
}


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def lanes_of(paths: list[str]) -> dict[str, list[str]]:
    """파일들을 갈래별로 나눈다. 어느 갈래도 아닌 것(docs/·최상위 md)은 뺀다."""
    found: dict[str, list[str]] = {}
    for path in paths:
        normalized = path.replace("\\", "/")
        for lane, prefixes in LANES.items():
            if normalized.startswith(prefixes):
                found.setdefault(lane, []).append(normalized)
                break
    return found


def staged_files() -> list[str]:
    """staged 파일 목록.

    **`-z`와 `core.quotepath=false`를 함께 쓴다.** 기본값에서 git은 한글 경로를
    `"rules/sources/ì..."`처럼 8진수로 감싸 내놓는다 — 그대로 받으면
    `rules/sources/`로 시작하지 않게 되어 이 저장소의 한글 폴더가 통째로 안 잡힌다
    (2026-09-08, 이 검사를 붙인 첫 커밋이 실제로 조용히 지나갔다).
    """
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=false", "diff", "--cached",
             "--name-only", "-z"],
            cwd=ROOT, capture_output=True, check=False)
    except OSError:
        return []
    return parse_z_output(out.stdout)


def parse_z_output(raw: bytes) -> list[str]:
    """`-z`로 받은 NUL 구분 목록을 파일 목록으로. 한글 경로가 그대로 나와야 한다."""
    text = raw.decode("utf-8", "replace")
    return [piece for piece in text.split(chr(0)) if piece.strip()]


def single_work_learned(paths: list[str]) -> list[str]:
    """학습값 파일 중 근거가 **한 작품뿐인** 것.

    규칙 12의 증거 기준 — 한 작품에서만 나온 것은 규정이 아니라 그 작품의 습관일
    수 있다. 파일을 못 읽거나 형식이 다르면 아무 말도 하지 않는다(모르는 것을
    지적으로 만들지 않는다).
    """
    try:
        import yaml
    except ImportError:
        return []
    out = []
    for path in paths:
        if not path.startswith("rules/learned/") or not path.endswith((".yaml", ".yml")):
            continue
        full = ROOT / path
        if not full.is_file():
            continue
        try:
            data = yaml.safe_load(full.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):
            continue
        works = (((data or {}).get("source") or {}).get("from") or {}).get("작품")
        if isinstance(works, list) and len(works) == 1:
            out.append(path)
    return out


def report(paths: list[str]) -> str | None:
    """할 말이 없으면 `None`."""
    found = lanes_of(paths)
    lines: list[str] = []

    if len(found) > 1:
        lines.append(f"갈래 {len(found)}개가 한 커밋에 섞여 있다(규칙 12 — "
                     f"갈래를 동시에 벌이지 않는다):")
        for lane, files in found.items():
            shown = ", ".join(files[:3]) + (f" 외 {len(files) - 3}개"
                                            if len(files) > 3 else "")
            lines.append(f"  {lane}: {shown}")
        lines.append("  한 갈래를 끝내고 확인받은 뒤 다음으로 넘어가는 것이 원칙이다.")

    single = single_work_learned(paths)
    if single and "코드" in found:
        lines.append("근거가 한 작품뿐인 학습값과 코드 수정이 함께 있다"
                     "(규칙 12 — 최소 2편):")
        for path in single[:4]:
            lines.append(f"  {path}")
        lines.append("  한 작품에서만 나온 값은 규정이 아니라 그 작품의 습관일 수 있다.")

    if not lines:
        return None
    lines.append("**막지 않는다.** 커밋 단위는 세션 단위가 아니라 근사치다 — "
                 "보고 판단한다.")
    return "\n".join(lines)


def main() -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="검사할 파일들. 없으면 staged 파일을 본다")
    a = ap.parse_args()

    text = report(a.paths or staged_files())
    if text:
        print("lanes_check: " + text)
    # **언제나 0이다.** 알리기만 한다.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
