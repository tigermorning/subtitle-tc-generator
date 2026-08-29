"""`docs/corpus_status.yaml`을 읽어 `--generate` 명령을 자동으로 조립한다.

**왜 필요한가.** `--genre variety` 같은 플래그를 사람이 매번 손으로 타이핑하면
빠뜨릴 수 있다 — 실제로 2026-08-28·2026-08-29 두 세션이 연속으로 이 플래그를
빠뜨렸다(예능A 15·16회). 원장(`docs/corpus_status.yaml`)에 이미 작품의
platform·genre와 회차별 kind(sdh/translation)·lang이 적혀 있으니, 그걸 읽어서
플래그를 조립하면 사람이 다시 타이핑할 일이 없어져 이 종류의 실수 자체가
구조적으로 사라진다.

    python tools/gen_from_ledger.py 예능A 15 sdh -o 출력.srt

**schema_version: 2** — 한 회차에 kind(sdh/translation)가 여럿일 수 있다
(2026-08-30, `docs/AGENT_INCIDENTS.md` 6번 — kind 하나만 모델링해서 다른
kind가 원장에서 통째로 안 보였던 사고 이후 스키마를 바꿈). 그래서 `kind`를
필수 위치 인자로 받는다.

끝나면 원장의 `kinds.<kind>.pipeline.tc_generated`를 자동으로 갱신한다(날짜·
플래그·출력 경로). `tc_verified`는 이 도구가 손대지 않는다 — 사람 판단이
들어가야 한다(CLAUDE.md 규칙 17). `text_polished`·`delivered`는 정답지가
없는 kind에서만 의미가 있다(규칙 13) — 이 도구는 아예 안 건드린다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "corpus_status.yaml"


def load_ledger() -> dict:
    return yaml.safe_load(LEDGER.read_text(encoding="utf-8")) or {}


def save_ledger(data: dict) -> None:
    LEDGER.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("work", help="docs/corpus_status.yaml의 works 키 (예: 예능A)")
    ap.add_argument("episode", help="episodes 키 (예: 15)")
    ap.add_argument("kind", choices=["sdh", "translation"], help="kinds 키")
    ap.add_argument("-o", "--out", type=Path, help="출력 경로(생략하면 .tmp/최종초안/ 아래 자동 생성)")
    ap.add_argument("--dry-run", action="store_true", help="명령만 보여주고 실행하지 않는다")
    args = ap.parse_args()

    data = load_ledger()
    work = (data.get("works") or {}).get(args.work)
    if not work:
        print(f"[오류] 원장에 없는 작품: {args.work} (있는 것: {', '.join((data.get('works') or {}).keys())})",
              file=sys.stderr)
        return 2
    ep = (work.get("episodes") or {}).get(str(args.episode))
    if not ep:
        print(f"[오류] {args.work}에 없는 회차: {args.episode}", file=sys.stderr)
        return 2
    kinds = ep.get("kinds") or {}
    kind_entry = kinds.get(args.kind)
    if not kind_entry:
        print(f"[오류] {args.work} {args.episode}회에 없는 kind: {args.kind} "
              f"(있는 것: {', '.join(kinds.keys()) or '없음'})", file=sys.stderr)
        return 2

    video = ROOT / ep["video"]
    if not video.is_file():
        print(f"[오류] 영상을 찾지 못했습니다: {video}", file=sys.stderr)
        return 2

    lang = kind_entry["lang"]  # 결과물(프로파일) 언어 — sdh는 원어와 같지만 translation은 다르다
    source_lang = work.get("source_lang")
    if not source_lang:
        print(f"[오류] {args.work}에 source_lang이 없습니다 — 영상 속 실제 발화 언어를 원장에 적어야 합니다.",
              file=sys.stderr)
        return 2
    out = (args.out or (ROOT / ".tmp" / "최종초안" /
                        f"{args.work}_{args.episode}회_{lang}{args.kind}_초안.srt")).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "checker", "--generate",
        "--video", str(video),
        "--whisper-lang", source_lang,
        "-p", work["platform"], "-l", lang, "-k", args.kind,
        "-o", str(out),
    ]
    if args.kind == "translation":
        cmd += ["--translate"]
    if work.get("genre"):
        cmd += ["--genre", work["genre"]]

    print("실행:", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if args.dry_run:
        return 0

    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    pipeline = kind_entry.setdefault("pipeline", {})
    pipeline["tc_generated"] = {
        "done": True,
        "date": date.today().isoformat(),
        "flags": " ".join(cmd[3:]),
        "output": str(out.relative_to(ROOT)),
    }
    save_ledger(data)
    print(f"\n원장 갱신 완료: {LEDGER.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
