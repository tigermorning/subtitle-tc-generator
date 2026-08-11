"""SubtitleEdit 북마크를 데이터로 바꾼다.

강사가 SE 북마크로 첨삭해 준 파일이 있다. 자막 번호와 지적이 짝지어 있으니, 그것이
곧 **전문가가 짚은 실패 사례 목록**이다. 규정 문서가 "무엇이 맞는지"를 말한다면
이쪽은 "무엇이 실제로 틀리는지"를 말한다 — 검사 규칙을 만들 때 더 값진 자료다.

    {"idx":15,"txt":"아웃점 너무 빠릅니다. 세 칸 정도 뒤로 밀어도 되겠어요."}
    {"idx":7,"txt":"<오역><br />8-9번 문장에 모두 may가 걸립니다..."}

**갈래를 나눈다.** 타임코드 지적과 번역 지적은 고칠 자리가 다르다. 타임코드는
`timing`·`regroup`의 값을 재는 자료가 되고, 번역·표기는 검사 규칙이나 교정기
백로그가 된다.

번호가 파일마다 0부터인지 1부터인지 다르다(SE가 저장한 그대로다). 자막 수를 넘는
번호가 나오면 0-기준으로 보고 다시 맞춘다 — 어림짐작이 아니라 확인 가능한 규칙이다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .model import Event
from .parsers import parse

# 강사가 직접 쓴 갈래 표시. 있으면 그것을 믿는다.
TAGGED = re.compile(r"<(오역|윤문|표기|맞춤법|스포팅|기타)>")

# 없으면 말로 가른다. **순서가 결과를 가른다.** 타임코드 낱말이 가장 좁고 분명해서
# 먼저 보고, 표기가 그다음, 번역이 마지막이다 — "이 표기의 의미가"처럼 낱말이
# 겹칠 때 더 좁은 갈래가 이겨야 한다.
KEYWORDS = (
    ("timecode", ("인점", "아웃점", "타임코드", "스파팅", "스포팅", "최소시간",
                  "간격", "프레임", "칸 정도", "자막이 끊기", "합치", "나누어",
                  "타이틀로 칩니다", "듀레이션")),
    ("notation", ("표기", "맞춤법", "띄어쓰기", "붙여 써", "붙여 씁", "고유명사",
                  "숫자", "지명", "말줄임표", "따옴표", "물음표", "느낌표", "쉼표",
                  "마침표", "하이픈", "달러", "단위")),
    ("translation", ("오역", "윤문", "의미", "번역", "말투", "어미", "존대", "반말",
                     "직역", "자연스럽", "문장", "대사")),
)


@dataclass
class Note:
    source: str          # 어느 파일에서 왔는지
    index: int           # 자막 번호(1-기준으로 맞춘 값)
    kind: str            # timecode | translation | notation | other
    text: str            # 지적 내용
    cue: Event | None = None   # 그 자막(있으면)

    def to_dict(self) -> dict:
        return {
            "source": self.source, "index": self.index, "kind": self.kind,
            "note": self.text,
            "cue_text": self.cue.text if self.cue else None,
            "start_ms": self.cue.start_ms if self.cue else None,
            "end_ms": self.cue.end_ms if self.cue else None,
        }


def clean(text: str) -> str:
    """SE가 넣는 `<br />`를 줄바꿈으로 돌리고 앞뒤를 정리한다."""
    return re.sub(r"\s*<br\s*/?>\s*", "\n", text).strip()


def classify(text: str) -> str:
    found = TAGGED.search(text)
    if found:
        label = found.group(1)
        return {"오역": "translation", "윤문": "translation",
                "표기": "notation", "맞춤법": "notation",
                "스포팅": "timecode"}.get(label, "other")
    for kind, words in KEYWORDS:
        if any(word in text for word in words):
            return kind
    return "other"


def read(path: Path) -> list[Note]:
    """북마크 파일 하나를 읽는다. 옆에 있는 자막 파일도 함께 본다."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    notes_raw = data.get("bookmarks") or []

    # `x.srt.SE.bookmarks` -> `x.srt`
    subtitle_path = path.with_suffix("")
    if subtitle_path.suffix == ".SE":
        subtitle_path = subtitle_path.with_suffix("")
    events = parse(subtitle_path) if subtitle_path.is_file() else []
    by_index = {e.index: e for e in events}

    # 0-기준 파일인지 확인한다. 근거는 둘이다 — **0번이 있거나**, 자막 수를 넘는
    # 번호가 있거나. 처음에는 `>= len(events)`로 봤다가 자막이 2개일 때 정당한
    # 2번을 0-기준으로 오해했다. 경계는 `>`가 맞다.
    indexes = [int(n.get("idx", 0)) for n in notes_raw]
    zero_based = bool(events) and bool(indexes) and (
        0 in indexes or max(indexes) > len(events))

    notes = []
    for raw in notes_raw:
        index = int(raw.get("idx", 0)) + (1 if zero_based else 0)
        text = clean(str(raw.get("txt", "")))
        if not text:
            continue
        notes.append(Note(subtitle_path.name, index, classify(text), text,
                          by_index.get(index)))
    return notes


def collect(folder: Path) -> list[Note]:
    """폴더 안의 북마크를 모두 모은다."""
    out: list[Note] = []
    for path in sorted(Path(folder).glob("*.bookmarks")):
        try:
            out.extend(read(path))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def summarize(notes: list[Note]) -> dict:
    counts: dict[str, int] = {}
    for note in notes:
        counts[note.kind] = counts.get(note.kind, 0) + 1
    return {"total": len(notes), "by_kind": counts,
            "with_cue": sum(1 for n in notes if n.cue)}
