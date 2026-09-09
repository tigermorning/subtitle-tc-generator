"""문서가 코드보다 낡지 않게 기계가 지킨다.

## 왜 필요한가

규칙 17은 "손대기 전에 `docs/HANDOFF.md` 6절·`docs/corpus_status.yaml`·메모리를
먼저 열어 보라"고 정한다. **그 파일들이 낡으면 체크리스트가 오히려 함정이 된다.**

2026-09-08에 실제로 그랬다. `docs/HANDOFF.md` 7절과 `docs/MVP.md`가

    `grep -rn "learned" checker/*.py` 0건 — 다음 세션은 여기부터 시작한다

라고 적어 두고 있었는데, 그 경로는 일주일 전(2026-09-01, `19141e2`)에 이미
만들어졌고 grep은 7건이 나온다. 하마터면 끝난 일을 다시 할 뻔했다(사고 1번과
같은 모양 — `docs/AGENT_INCIDENTS.md`).

규칙 9(시험 통과 후 커밋)가 글로는 세 번 뚫리고 훅으로는 한 번도 안 뚫렸다.
같은 방식을 문서에 적용한다 — **문서가 스스로 증명할 수 있는 주장만** 기계가
확인한다.

## 무엇을 확인하나

    경로       문서가 백틱으로 가리키는 저장소 파일이 실제로 있는가
    grep 주장   문서가 "`grep ... ` N건"이라고 적었으면 지금도 N건인가
    살아있는 수  "훅이 도는 것은 N건"처럼 **지금 상태를 말하는** 숫자가 맞는가

## 무엇을 확인하지 않나

**과거 기록은 건드리지 않는다.** `docs/BACKLOG.md`·`docs/AGENT_INCIDENTS.md`는
그때 그랬다는 기록이라 낡는 것이 정상이다(경로만 본다). "테스트 817건 통과" 같은
문장도 그 시점의 사실이라 지금 수와 달라야 맞다.

살아있는 숫자는 **아래 `LIVE_COUNTS`에 손으로 등록한 것만** 본다. 문장을 보고
"이건 지금 상태 같다"고 기계가 짐작하면 과거 기록까지 흔들어 놓는다(규칙 4 —
추정으로 자동 판정하지 않는다). 새로 그런 숫자를 적으면 여기 한 줄 등록한다.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 지금 상태를 말하는 문서. 경로·grep·숫자를 다 본다.
LIVING = ["CLAUDE.md", "AGENTS.md", "README.md",
          "docs/HANDOFF.md", "docs/MVP.md", "docs/PRD.md"]
# 그때의 기록. 낡는 것이 정상이라 **경로만** 본다.
HISTORICAL = ["docs/BACKLOG.md", "docs/AGENT_INCIDENTS.md",
              "docs/COMMERCIALIZATION.md", "docs/SE_PLUGIN.md",
              "docs/TRANSLATION_ARCHITECTURE.md", "docs/SE_WORKFLOW_AUTOMATION.md"]

# 저장소 안을 가리키는 경로만 본다. 옆 리포(korean-subtitle-corrector)나
# 임시 폴더(.tmp/·.work/)를 가리키는 표기는 여기 없어서 저절로 빠진다.
TOP_DIRS = ("checker/", "app/", "tools/", "rules/", "docs/", "tests/",
            "plugin/", "examples/", "bin/", "models/", "corpus/")

# 옆 리포(korean-subtitle-corrector)의 파일을 가리키는 줄은 뺀다. 규칙 0 — 이
# 프로젝트는 둘이고, 저쪽 경로가 여기 없는 것은 낡은 게 아니라 당연한 것이다.
OTHER_REPO = ("교정기", "korean-subtitle-corrector", "옆 리포", "korean-corrector")

PATH_IN_BACKTICKS = re.compile(
    r"`([A-Za-z0-9_./\-가-힣 ]+\.(?:py|yaml|yml|md|json|bat|srt|spec|txt))`")
# "`grep -rn "learned" checker/*.py` 0건" 꼴. 명령과 건수가 같은 줄에 있을 때만 본다.
GREP_CLAIM = re.compile(
    r"`grep\s+-[a-zA-Z]*\s+\"([^\"]+)\"\s+([^`]+)`[^\n]{0,40}?(\d+)\s*건")

# 지금 상태를 말하는 숫자. `(파일, 정규식, 종류)` — 종류는 아래 설명 참고.
#   system : 시스템 파이썬으로 도는 시험 수(훅이 도는 수). --test-count로 받는다
#   gui    : PySide6까지 도는 수. 훅은 못 세므로 system보다 큰지만 본다
LIVE_COUNTS = [
    ("CLAUDE.md", r"훅이 도는 것은 (\d+)건", "system"),
    ("CLAUDE.md", r"PySide6까지 도는\s*\n?\s*(\d+)건", "gui"),
    ("README.md", r"tests/run_tests\.py\s*#\s*(\d+)건", "system"),
    ("README.md", r"tests\\run_tests\.py\"\s*#\s*(\d+)건", "gui"),
]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def check_paths(names: list[str]) -> list[str]:
    """문서가 가리키는 저장소 파일이 실제로 있는지."""
    bad = []
    for name in names:
        path = ROOT / name
        if not path.is_file():
            continue
        lines = _read(name).splitlines()
        for i, line in enumerate(lines, 1):
            # 앞 줄까지 함께 본다 — 문서가 80칸에서 접히기 때문에 "교정기의"가
            # 앞 줄에 있고 경로가 다음 줄에 오는 일이 흔하다.
            context = " ".join(lines[max(0, i - 2):i])
            if "docs-check: 무시" in context or any(k in context for k in OTHER_REPO):
                continue
            for match in PATH_IN_BACKTICKS.finditer(line):
                target = match.group(1)
                if not target.startswith(TOP_DIRS):
                    continue
                if not (ROOT / target).exists():
                    bad.append(f"{name}:{i} 없는 경로를 가리킨다 — {target}")
    return bad


def _grep_count(pattern: str, target: str) -> int:
    """문서가 적어 둔 grep을 실제로 돌려 몇 줄인지 센다."""
    files: list[Path] = []
    for piece in target.split():
        files += sorted(ROOT.glob(piece))
    hits = 0
    needle = re.compile(pattern)
    for path in files:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        hits += sum(1 for line in text.splitlines() if needle.search(line))
    return hits


def _line_of(text: str, needle: str) -> int:
    """`needle`이 처음 나오는 줄 번호. 못 찾으면 0."""
    for i, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return i
    return 0


def check_grep_claims(names: list[str]) -> list[str]:
    """"`grep ...` N건"이라고 적었으면 지금도 N건인지.

    **줄바꿈을 넘어서도 잡는다.** 문서는 80칸에서 줄을 접기 때문에 명령과 건수가
    서로 다른 줄에 놓이는 일이 흔하다 — 줄 단위로만 보면 정작 중요한 주장을
    놓친다(2026-09-08에 낡은 채 남아 있던 그 문장이 정확히 그 꼴이었다).
    """
    bad = []
    for name in names:
        path = ROOT / name
        if not path.is_file():
            continue
        text = _read(name)
        joined = re.sub(r"\s*\n\s*", " ", text)
        for pattern, target, claimed in GREP_CLAIM.findall(joined):
            # 명령 전체로 자리를 찾는다. 패턴 글자만으로 찾으면(예: "learned")
            # 문서 앞쪽의 무관한 줄이 잡힌다.
            i = _line_of(text, f'"{pattern}"') or _line_of(text, pattern)
            near = text.splitlines()[max(0, i - 2):i + 1]
            if any("docs-check: 무시" in line for line in near):
                continue
            got = _grep_count(pattern, target.strip())
            if got != int(claimed):
                bad.append(
                    f"{name}:{i} grep 주장이 낡았다 — "
                    f"'{pattern}' {target.strip()}: 적힌 값 {claimed}건, 지금 {got}건")
    return bad


def check_live_counts(test_count: int | None) -> list[str]:
    """지금 상태를 말하는 숫자가 맞는지. 등록된 것만 본다."""
    bad = []
    if test_count is None:
        return bad
    for name, pattern, kind in LIVE_COUNTS:
        path = ROOT / name
        if not path.is_file():
            continue
        text = _read(name)
        match = re.search(pattern, text)
        if not match:
            bad.append(f"{name} 등록된 숫자를 못 찾았다 — 문장이 바뀌었으면 "
                       f"`tools/docs_check.py`의 LIVE_COUNTS도 고친다: /{pattern}/")
            continue
        value = int(match.group(1))
        if kind == "system" and value != test_count:
            bad.append(f"{name} 시험 수가 낡았다 — 적힌 값 {value}건, 지금 {test_count}건")
        # GUI 시험은 훅이 못 센다(PySide6가 없다). "더 많아야 한다"(>)가 아니라
        # "적어도 시스템만큼은 돌아야 한다"(>=)가 진짜 불변식이다 — agent/처럼
        # PySide6와 무관한 시험이 늘면 시스템·GUI 양쪽에 똑같이 더해지므로 둘이
        # 같아지는 게 정상이다(2026-09-09 실제로 겪음 — 전엔 `<=`라 이 정상
        # 상태를 오류로 잘못 잡았다).
        if kind == "gui" and value < test_count:
            bad.append(f"{name} PySide6 시험 수가 시스템 시험 수({test_count})보다 "
                       f"작다 — 적힌 값 {value}건. venv로 돌려 실제 수로 고친다")
    return bad


def fix_counts(test_count: int) -> list[str]:
    """등록된 시험 수를 지금 값으로 고쳐 쓴다.

    **왜 있나.** 시험을 하나 보태면 그 숫자가 곧바로 낡는다. 막기만 하고 고칠
    길이 없으면 사람이 검사를 꺼 버린다 — 규칙 9의 훅이 살아남은 이유는 고치는
    비용이 작았기 때문이다. `system` 종류만 고친다. PySide6 쪽은 이 기계가 셀 수
    없으므로 사람이 venv로 돌려 넣는다.
    """
    fixed = []
    for name, pattern, kind in LIVE_COUNTS:
        if kind != "system":
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        text = _read(name)
        match = re.search(pattern, text)
        if not match or int(match.group(1)) == test_count:
            continue
        start, end = match.span(1)
        path.write_text(text[:start] + str(test_count) + text[end:], encoding="utf-8")
        fixed.append(f"{name}: {match.group(1)}건 -> {test_count}건")
    return fixed


def _force_utf8_output() -> None:
    """Windows 콘솔 기본 인코딩(cp949)에서 메시지가 깨지지 않게 한다.

    **이 도구는 커밋을 막는 자리에서 말한다.** 막힌 이유가 깨진 글자로 나오면
    사람은 `--no-verify`로 넘어가 버린다 — 규칙 10이 말하는 그 자리다
    (`checker/cli.py`의 `_force_utf8_output`과 같은 이유·같은 방식).
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main() -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--test-count", type=int, default=None,
                    help="방금 돌린 시험 수(훅이 넘긴다). 없으면 숫자 확인은 건너뛴다")
    ap.add_argument("--fix-counts", action="store_true",
                    help="등록된 시험 수를 --test-count 값으로 고쳐 쓴다")
    a = ap.parse_args()

    if a.fix_counts:
        if a.test_count is None:
            print("--fix-counts에는 --test-count가 필요합니다.", file=sys.stderr)
            return 2
        for row in fix_counts(a.test_count):
            print(f"docs_check: 고침 — {row}")

    problems = (check_paths(LIVING + HISTORICAL)
                + check_grep_claims(LIVING)
                + check_live_counts(a.test_count))
    if not problems:
        print("docs_check: 문서가 코드와 맞는다.")
        return 0

    print(f"docs_check: 낡은 곳 {len(problems)}군데")
    for row in problems:
        print(f"  - {row}")
    print("\n  고치거나, 지금은 맞는 표기인데 걸렸으면 그 줄에 "
          "`docs-check: 무시`를 남긴다.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
