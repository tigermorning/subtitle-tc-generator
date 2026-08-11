"""원어 대본을 읽는다 — txt·docx·pdf·자막 파일.

**대본은 자막 파일로 오지 않는다.** 실무에서 받는 것은 워드 문서이거나 텍스트이고,
때로는 PDF다(사용자 지적 2026-08-12). 자막 형식만 열 수 있으면 대본을 쓸 수 없다.

읽고 나서 하는 일은 `generate.read_script`와 같다 — 화자 표시와 지문을 떼고 대사만
남긴다("스크립트에서는 대사만 딸 것!", 작업자 자료 100행).

**의존성을 늘리지 않는다.** docx는 zip 안의 XML이라 표준 라이브러리로 읽는다.
PDF만은 남의 힘을 빌리는데(`pypdf`), 없으면 없다고 말하고 다른 형식을 권한다 —
없는 기능 때문에 프로그램이 멈추지는 않는다.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

DOCX_TEXT = re.compile(r"<w:t[^>]*>(.*?)</w:t>", re.S)
DOCX_PARAGRAPH = re.compile(r"<w:p[ >].*?</w:p>", re.S)
DOCX_BREAK = re.compile(r"<w:(?:br|cr)\s*/>")
ENTITIES = (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"))

SUBTITLE_SUFFIXES = (".srt", ".vtt")
SCRIPT_SUFFIXES = (".txt", ".md", ".docx", ".pdf")


class ScriptUnavailable(Exception):
    """읽을 수 없는 형식이거나 읽는 도구가 없다."""


def _unescape(text: str) -> str:
    for entity, char in ENTITIES:
        text = text.replace(entity, char)
    return text


def read_text(path: Path) -> str:
    """글자를 읽는다. **한국어 파일은 cp949로 오는 경우가 흔하다.**"""
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def read_docx(path: Path) -> str:
    """워드 문서에서 글자만 뽑는다. 문단은 줄로 남긴다.

    문단 구분을 지키는 이유: 대본에서 한 문단이 한 대사인 경우가 많다. 통째로
    이어 붙이면 어디서 끊어야 할지 알 수 없게 된다.
    """
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.endswith("document.xml")]
        if not names:
            raise ScriptUnavailable(f"워드 문서로 보이지 않습니다: {path.name}")
        xml = archive.read(names[0]).decode("utf-8", "replace")

    lines = []
    for paragraph in DOCX_PARAGRAPH.findall(xml):
        paragraph = DOCX_BREAK.sub("\n", paragraph)
        text = "".join(_unescape(t) for t in DOCX_TEXT.findall(paragraph))
        lines.append(text.strip())
    return "\n".join(lines)


def read_pdf(path: Path) -> str:
    """PDF에서 글자를 뽑는다. 없는 도구는 없다고 말한다."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ScriptUnavailable(
            "PDF를 읽으려면 pypdf가 필요합니다(pip install pypdf). "
            "지금은 txt나 docx로 저장해 주세요.") from exc

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def read_any(path: Path) -> str:
    """형식을 보고 알맞게 읽는다."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return read_docx(path)
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix in SUBTITLE_SUFFIXES:
        from .parsers import parse
        return "\n\n".join(event.text for event in parse(path))
    return read_text(path)


def read_lines(path: Path):
    """대사 목록(`generate.ScriptLine`)으로 읽는다.

    자막 파일로 오면 자막 하나가 한 대사다. 문서로 오면 빈 줄로 나뉜 덩어리가
    한 대사다 — 대본의 줄바꿈은 종이 폭 때문이지 대사가 끊긴 자리가 아니다.
    """
    from .generate import read_script

    path = Path(path)
    text = read_any(path)
    if path.suffix.lower() not in SUBTITLE_SUFFIXES and "\n\n" not in text:
        # 빈 줄이 없는 대본은 한 줄이 한 대사다. 그대로 두면 통째로 한 덩어리가 된다.
        text = "\n\n".join(line for line in text.split("\n") if line.strip())

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(text)
        temporary = Path(handle.name)
    try:
        return read_script(temporary)
    finally:
        temporary.unlink(missing_ok=True)


def file_filter() -> str:
    """파일 고르기 창에 쓸 거르개."""
    return ("대본·자막 (*.txt *.md *.docx *.pdf *.srt *.vtt);;"
            "워드 (*.docx);;텍스트 (*.txt *.md);;PDF (*.pdf);;"
            "자막 (*.srt *.vtt);;모든 파일 (*.*)")
