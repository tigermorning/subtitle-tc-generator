"""KNP 시트를 읽는다 — 작업자가 이미 만들어 둔 용어집.

KNP(Key Terms and Phrases)는 작업 전에 채우는 표다. 인명·지명·기관명과 그 한국어
표기, 존댓말/반말 관계가 여기 정리된다. 작업자 자료의 표현으로는 "용어, 존대, 반대를
통일해 작품의 통일성 유지".

**이미 있는 것을 다시 만들게 하지 않는다.** 번역기에 용어집을 따로 입력하라고 하면
아무도 안 쓴다. 작업자가 어차피 만드는 KNP 파일을 그대로 먹는다.

엑셀을 읽는 데 외부 라이브러리를 쓰지 않는다. xlsx는 zip 안의 XML이라 표준 라이브러리로
읽을 수 있고, 의존성 하나가 늘면 SE 플러그인 쪽 설치가 그만큼 까다로워진다.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

# xlsx는 파일마다 이름공간 접두사가 붙기도 하고 안 붙기도 한다(`<t>` / `<x:t>`).
TEXT = re.compile(r"<(?:\w+:)?t[^>]*>(.*?)</(?:\w+:)?t>", re.S)
ROW = re.compile(r"<(?:\w+:)?row[^>]*>(.*?)</(?:\w+:)?row>", re.S)
CELL = re.compile(r"<(?:\w+:)?c\b([^>]*)>(.*?)</(?:\w+:)?c>|<(?:\w+:)?c\b([^>]*)/>", re.S)
VALUE = re.compile(r"<(?:\w+:)?v[^>]*>(.*?)</(?:\w+:)?v>", re.S)
INLINE = re.compile(r"<(?:\w+:)?is>(.*?)</(?:\w+:)?is>", re.S)

ENTITIES = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"))

SOURCE_HEADERS = ("source language", "source", "원어", "영어")
TARGET_HEADERS = ("target language", "target", "한국어", "번역")


def _unescape(text: str) -> str:
    for entity, char in ENTITIES:
        text = text.replace(entity, char)
    return text.strip()


def read_sheet(path: Path) -> list[list[str]]:
    """첫 시트를 표로 읽는다. 셀은 문자열로만 돌려준다."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            raw = archive.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            shared = [_unescape(t) for t in TEXT.findall(raw)]
        sheet_name = next((n for n in names
                           if n.startswith("xl/worksheets/") and n.endswith(".xml")), None)
        if not sheet_name:
            return []
        sheet = archive.read(sheet_name).decode("utf-8", "replace")

    rows: list[list[str]] = []
    for row_xml in ROW.findall(sheet):
        cells: list[str] = []
        for attrs, body, empty_attrs in CELL.findall(row_xml):
            attributes = attrs or empty_attrs or ""
            kind = re.search(r't="(\w+)"', attributes)
            found = VALUE.search(body or "")
            if kind and kind.group(1) == "s" and found:
                index = int(found.group(1))
                cells.append(shared[index] if 0 <= index < len(shared) else "")
            elif kind and kind.group(1) == "inlineStr":
                inline = INLINE.search(body or "")
                cells.append(" ".join(_unescape(t) for t in TEXT.findall(inline.group(1)))
                             if inline else "")
            else:
                cells.append(_unescape(found.group(1)) if found else "")
        if any(cells):
            rows.append(cells)
    return rows


def read_terms(path: Path) -> dict[str, str]:
    """`원어 -> 한국어` 짝을 뽑는다.

    머리글 줄을 찾아 어느 칸이 원어이고 어느 칸이 한국어인지 정한다. 칸 순서가
    파일마다 다르기 때문이다 — 자리로 짐작하면 인명 칸을 용어로 넣게 된다.
    """
    rows = read_sheet(Path(path))
    source_column = target_column = None
    terms: dict[str, str] = {}

    for row in rows:
        lowered = [cell.strip().lower() for cell in row]
        if source_column is None:
            for i, cell in enumerate(lowered):
                if cell in SOURCE_HEADERS:
                    source_column = i
                elif cell in TARGET_HEADERS:
                    target_column = i
            if source_column is not None and target_column is not None:
                continue        # 머리글 줄 자체는 용어가 아니다
            source_column = target_column = None
            continue

        if target_column is None or max(source_column, target_column) >= len(row):
            continue
        source, target = row[source_column].strip(), row[target_column].strip()
        # 한쪽만 있는 줄은 아직 채우는 중이다. 반쪽짜리를 용어로 삼지 않는다.
        if source and target and source.lower() not in SOURCE_HEADERS:
            terms[source] = target
    return terms


def find_for(subtitle: Path) -> Path | None:
    """자막 옆에서 KNP 파일을 찾는다.

    실무에서 같은 폴더에 `..._KNP.xlsx`로 둔다. 경로를 손으로 넣게 하면 아무도 안
    쓴다 — 옆에 있으면 그냥 쓴다.
    """
    subtitle = Path(subtitle)
    folder = subtitle.parent
    stem = subtitle.stem
    for tag in (".fixed", ".draft", "_ko_TL", "_ko_TC", "_TL", "_TC"):
        if stem.endswith(tag):
            stem = stem[: -len(tag)]

    found = sorted(folder.glob("*KNP*.xlsx"))
    if not found:
        return None
    # 이름이 가장 비슷한 것을 고른다. 한 폴더에 회차가 여럿 있을 수 있다.
    same_stem = [p for p in found if stem and stem in p.stem]
    return (same_stem or found)[0]
