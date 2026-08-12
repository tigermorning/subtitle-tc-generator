"""단계마다 낸 것을 남긴다 — **깨졌을 때 처음부터 하지 않게.**

15분 걸린 번역이 3차에서 깨지면 지금은 처음부터다. GUI는 아무것도 남기지 않고
메모리에서만 돌았고, CLI는 `.source.srt`·`.draft.srt`·`.notes.srt`·`.review.srt`·
`.ko.srt`·`.fixed.srt`로 파편적이라 어느 것이 어느 단계인지 규칙이 없었다.

    <자막이름>.work/
        manifest.json      단계별로: 모델, 시각, 걸린 시간, 바뀐 줄, 멈춘 이유
        01-source.json     번호별 원문 — 감수가 오역을 보려면 반드시 필요하다
        02-first.srt       1차 번역
        03-revise-2.srt    회차마다 따로 — 회차 사이를 견줄 수 있다
        03-revise-3.srt
        04-polish.srt

## 지키는 것

- **원본을 덮어쓰지 않는다**(규칙 7). 폴더를 따로 만들고 그 안에만 쓴다.
- **타임코드는 첫 단계에서 굳는다.** 이후 단계가 옮기면 저장할 때 잡아 기록한다.
  받은 타임코드를 건드리는 것이 실무에서 가장 비싼 사고다(규칙 8).
- **전부 로컬이다.** 이 모듈은 네트워크를 쓰지 않는다.
- **터지지 않는다.** 남기기가 실패해도 본 작업이 멈추면 안 된다 — 남기는 것은
  보험이고, 보험이 본체를 죽이면 안 된다.

## 왜 manifest가 필요한가

파일 이름만으로는 "어느 모델로 돌렸는지", "몇 분 걸렸는지", "왜 거기서 멈췄는지"를
알 수 없다. 단계별 모델을 다르게 쓸 수 있게 하려면 그 기록이 있어야 하고, 수렴이
상한에 걸려 멈춘 것과 다 끝나서 멈춘 것도 구분해 남아야 한다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .model import Event
from .parsers import parse
from .writers import write_srt

MANIFEST = "manifest.json"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Work:
    """한 작품의 작업 폴더. **읽고 쓰는 것만 한다** — 판단은 부르는 쪽이 한다."""

    def __init__(self, root: Path):
        self.root = Path(root)

    # ------------------------------------------------------------ 만들기
    @classmethod
    def beside(cls, path: Path) -> "Work":
        """자막·영상 옆에 `<이름>.work/`를 잡는다. 만들지는 않는다."""
        path = Path(path)
        return cls(path.with_suffix("").with_name(path.stem + ".work"))

    def ensure(self) -> "Work":
        self.root.mkdir(parents=True, exist_ok=True)
        return self

    # ------------------------------------------------------------ manifest
    def manifest(self) -> dict:
        """지금까지의 기록. 없으면 빈 것을 돌려준다."""
        path = self.root / MANIFEST
        if not path.is_file():
            return {"created": _now(), "steps": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # **손으로 고치다 깨뜨릴 수 있다.** 깨진 기록 때문에 작업이 멈추면 안 된다.
            return {"created": _now(), "steps": [], "note": "기록이 깨져 새로 시작합니다"}
        if not isinstance(data, dict):
            return {"created": _now(), "steps": []}
        data.setdefault("steps", [])
        return data

    def _write_manifest(self, data: dict) -> None:
        try:
            self.ensure()
            (self.root / MANIFEST).write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass                    # 남기기가 본 작업을 죽이지 않는다

    # ------------------------------------------------------------ 쓰기
    def save(self, step: str, events: list[Event], *, model: str = "",
             seconds: float | None = None, note: str = "",
             extra: dict | None = None) -> dict:
        """단계 결과를 남긴다. 남긴 기록(사전)을 돌려준다.

        **타임코드가 첫 단계와 다르면 기록에 남긴다.** 예외를 올리지 않는다 — 저장은
        보험이고, 막을지 말지는 부르는 쪽이 정한다(규칙 8을 지키는 것은 어댑터의 일).
        """
        entry: dict = {"step": step, "at": _now(), "count": len(events)}
        if model:
            entry["model"] = model
        if seconds is not None:
            entry["seconds"] = round(seconds, 1)
        if note:
            entry["note"] = note
        if extra:
            entry.update(extra)

        data = self.manifest()
        first = data["steps"][0]["timecodes"] if data["steps"] else None
        now_tc = [[e.index, e.start_ms, e.end_ms] for e in events]
        if first is None:
            # **첫 단계가 타임코드를 굳힌다.** 이후 단계는 이것과 견준다.
            entry["timecodes"] = now_tc
        elif now_tc != first:
            moved = [row[0] for row, was in zip(now_tc, first) if row != was]
            entry["timecodes_moved"] = moved[:20]
            entry["timecodes_moved_count"] = (
                len(moved) if len(now_tc) == len(first)
                else abs(len(now_tc) - len(first)))

        try:
            self.ensure()
            out = self.root / f"{step}.srt"
            write_srt(events, out)
            entry["file"] = out.name
        except OSError as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"

        data["steps"].append(entry)
        self._write_manifest(data)
        return entry

    def save_source(self, source: dict[int, str], step: str = "01-source") -> None:
        """번호별 원문. **감수가 오역을 보려면 반드시 있어야 한다.**"""
        try:
            self.ensure()
            (self.root / f"{step}.json").write_text(
                json.dumps({str(k): v for k, v in source.items()},
                           ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    def read_source(self, step: str = "01-source") -> dict[int, str]:
        path = self.root / f"{step}.json"
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        out = {}
        for key, value in (raw or {}).items():
            try:
                out[int(key)] = value
            except (TypeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------ 읽기
    def steps(self) -> list[str]:
        """남아 있는 단계 이름. 남긴 순서를 지킨다."""
        return [s["step"] for s in self.manifest()["steps"] if s.get("file")]

    def read(self, step: str) -> list[Event]:
        """단계 결과를 되읽는다. 없으면 빈 목록."""
        path = self.root / f"{step}.srt"
        if not path.is_file():
            return []
        try:
            return parse(path)
        except Exception:
            return []

    def last(self) -> tuple[str, list[Event]]:
        """마지막으로 남긴 단계와 그 자막. **여기서 이어 하면 된다.**"""
        for entry in reversed(self.manifest()["steps"]):
            if entry.get("file"):
                events = self.read(entry["step"])
                if events:
                    return entry["step"], events
        return "", []

    def summary(self) -> str:
        """사람이 읽는 한 문단. 어디까지 됐고 무엇으로 돌렸는지."""
        data = self.manifest()
        steps = data["steps"]
        if not steps:
            return "남긴 단계가 없습니다."
        lines = [f"작업 폴더: {self.root}"]
        for entry in steps:
            bits = [f"자막 {entry.get('count', 0)}개"]
            if entry.get("model"):
                bits.append(entry["model"])
            if entry.get("seconds") is not None:
                bits.append(f"{entry['seconds']}초")
            if entry.get("changed") is not None:
                bits.append(f"{entry['changed']}곳 고침")
            lines.append(f"  {entry['step']:16} {' · '.join(bits)}")
            if entry.get("note"):
                lines.append(f"                   {entry['note']}")
            if entry.get("timecodes_moved_count"):
                # 숨기지 않는다. 받은 타임코드를 건드리는 것이 가장 비싼 사고다.
                lines.append(f"                   [경고] 타임코드가 "
                             f"{entry['timecodes_moved_count']}곳 움직였습니다: "
                             + ", ".join(f"#{i}" for i in entry.get("timecodes_moved", [])[:5]))
            if entry.get("error"):
                lines.append(f"                   [오류] {entry['error']}")
        return "\n".join(lines)


def diff(before: list[Event], after: list[Event]) -> list[dict]:
    """두 단계 사이에 바뀐 자막. 회차를 견주는 데 쓴다."""
    by_index = {e.index: e.text for e in before}
    out = []
    for event in after:
        was = by_index.get(event.index)
        if was is not None and was != event.text:
            out.append({"event_index": event.index, "before": was, "after": event.text})
    return out
