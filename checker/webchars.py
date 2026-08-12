"""등장인물 정보를 밖에서 찾아온다 — **작품 제목과 인물 이름만 내보낸다.**

작업자 자료가 이 조사를 왜 하는지 못 박아 두었다(`작업 기본 원칙` 인물 성격 항목):

> 인물 성격 파악에 따른 말투, 단어 설정이 중요함. 번역자가 생각할 때 자연스러운
> 자막을 쓰게 되면, **모든 인물들의 말투가 번역가의 말투로 설정되었다는 뜻**이기
> 때문에 좋은 번역이 아님. 자막을 만들 때 불편한 것이 정상!!
> (ex.) 성별, 나이, 직업, 경력, 싸가지 없는 성격, 비꼬기 좋아하는 성격 등

그래서 딸 항목이 정해져 있다 — 지어낸 목록이 아니다.

## 지키는 것

`webterms.py`와 같은 원칙이다. 다만 인물 이름은 지명보다 위험하다 — 흔치 않은
이름은 그 자체로 작품을 알려 준다. `webterms`의 첫머리도 그 점을 적어 두었다
("등장인물의 흔치 않은 이름이라면 이야기가 다르다 — 그 판단은 사람이 한다").

    ① **대사·대본은 어떤 경우에도 나가지 않는다.** 나가는 것은 작품 제목과 인물
       이름뿐이다.
    ② **기본은 꺼져 있다.** 부르는 쪽이 명시적으로 켜야 돈다.
    ③ **무엇을 보냈는지 전부 기록한다**(`sent()`).
    ④ **위키를 짐작하지 않는다.** 슬러그를 추측하면 엉뚱한 작품의 위키를 읽고,
       엉뚱한 인물 정보는 없는 것보다 나쁘다. 사람이 지정한다.

사진은 **주소와 라이선스만 가져온다.** 저작권물이므로 납품 문서에 동봉할지는
작업자가 판단한다 — 판단할 재료를 함께 낸다.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = ("subtitle-tc-generator/0.1 (local subtitle tool; "
              "https://github.com/tigermorning/subtitle-tc-generator)")

# 밖으로 내보낸 것을 남긴다. 사용자가 무엇이 나갔는지 확인할 수 있어야 한다.
_SENT: list[str] = []


def sent() -> list[str]:
    """이번 실행에서 밖으로 내보낸 낱말 목록. **대사는 여기에 들어올 수 없다.**"""
    return list(_SENT)


def forget() -> None:
    _SENT.clear()


def api_of(wiki: str) -> str:
    """위키 주소를 API 주소로 바꾼다.

    `breakingbad` -> `https://breakingbad.fandom.com/api.php`
    `https://breakingbad.fandom.com/ko` -> `.../ko/api.php`  (언어판 그대로 존중)
    """
    wiki = wiki.strip().rstrip("/")
    if not wiki:
        raise ValueError("위키를 지정해야 합니다")
    if wiki.startswith(("http://", "https://")):
        return wiki if wiki.endswith("api.php") else f"{wiki}/api.php"
    if "." in wiki:
        return f"https://{wiki}/api.php"
    return f"https://{wiki}.fandom.com/api.php"


def _call(api: str, params: dict, timeout: int = 20) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json"})
    request = urllib.request.Request(f"{api}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


# ---------------------------------------------------------------- 인포박스 읽기

# 자료가 이름 붙인 항목을 위키 인포박스의 흔한 키에 잇는다. **키를 짐작해 넓히지
# 않는다** — 엉뚱한 칸을 채우면 사람이 그것을 믿는다.
FIELD_KEYS = {
    "gender": ("gender", "sex", "성별"),
    "age": ("age", "나이", "birth", "born", "birthday", "생년월일"),
    "job": ("occupation", "job", "profession", "role", "직업", "직책"),
    "career": ("affiliation", "affiliations", "rank", "employer", "team",
               "organization", "경력", "소속"),
    "family": ("family", "relatives", "spouse", "children", "parents", "가족"),
}


def parse_infobox(wikitext: str) -> dict[str, str]:
    """인포박스의 `키 = 값`을 전부 딴다. **고르지 않고 다 낸다.**

    팬덤 위키는 인포박스 이름과 칸 이름이 작품마다 다르다. 우리가 아는 키만 딴 뒤
    나머지를 버리면 사람이 볼 재료가 사라진다 — 다 내고 고르는 것은 위에서 한다.
    """
    start = re.search(r"\{\{\s*(?:[Ii]nfobox|[^|}\n]*[Ii]nfobox)", wikitext)
    if not start:
        return {}

    # 중괄호 짝을 세어 인포박스 끝을 찾는다. 안에 템플릿이 또 들어 있는 경우가 흔해서
    # 첫 `}}`로 자르면 절반만 읽는다.
    depth, i = 0, start.start()
    while i < len(wikitext):
        if wikitext.startswith("{{", i):
            depth += 1
            i += 2
        elif wikitext.startswith("}}", i):
            depth -= 1
            i += 2
            if depth == 0:
                break
        else:
            i += 1
    body = wikitext[start.start():i]

    out: dict[str, str] = {}
    # 한 단계 아래 템플릿·링크 안의 `|`는 칸 구분이 아니다. 깊이를 세며 자른다.
    depth, bracket, buf, parts = 0, 0, [], []
    for ch in body[2:-2]:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket -= 1
        if ch == "|" and depth == 0 and bracket == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))

    for part in parts[1:]:                     # [0]은 템플릿 이름이다
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().lower()
        value = _plain(value)
        if key and value:
            out[key] = value
    return out


def _untemplate(text: str) -> str:
    """`{{틀}}`을 편다. **안쪽 내용을 지우지 않는다.**

    처음에는 `{{...}}`를 통째로 지웠는데 그러면 목록 틀에 싸인 값이 사라졌다 —
    `affiliation = {{Plainlist| * Gray Matter * Los Pollos Hermanos}}`가 빈칸이 되어
    경력 정보를 통째로 버렸다.

    규칙: **맨 인수는 내용이고 `키=값` 인수는 메타정보다.** 목록 틀의 항목은 맨
    인수로 오고, `{{cite web|url=...|title=...}}` 같은 각주 틀은 전부 `키=값`이라
    자연히 빠진다.
    """
    for _ in range(8):                      # 중첩은 몇 겹 안 된다. 무한 루프는 막는다
        found = re.search(r"\{\{([^{}]*)\}\}", text)
        if not found:
            break
        parts = found.group(1).split("|")[1:]
        kept = " ".join(p for p in parts if "=" not in p)
        text = text[: found.start()] + " " + kept + " " + text[found.end():]
    return text


def _plain(wikitext: str) -> str:
    """위키 표기를 사람이 읽는 글자로. **못 지우는 표기는 남긴다** — 지우려다 뜻을 깎지 않는다."""
    text = wikitext
    text = re.sub(r"<ref[^>]*?/>", "", text)
    text = re.sub(r"<ref[^>]*?>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    # [[문서|보이는 글자]] -> 보이는 글자
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[|\]\]", "", text)
    text = text.replace("'''", "").replace("''", "")
    text = _untemplate(text)
    text = re.sub(r"\s+", " ", text)
    # 목록 항목 표시가 글 속에 남으면 읽기 어렵다. 가름표로 바꾼다.
    text = re.sub(r"\s*[*•]\s*", " / ", text)
    return text.strip(" /*•-")


def pick_fields(infobox: dict[str, str]) -> dict[str, str]:
    """아는 키만 자료가 이름 붙인 항목으로 옮긴다. 나머지는 부르는 쪽이 원본으로 본다."""
    out: dict[str, str] = {}
    for our, keys in FIELD_KEYS.items():
        for key in keys:
            if key in infobox and infobox[key]:
                out[our] = infobox[key]
                break
    return out


# ---------------------------------------------------------------- 조회

@dataclass
class CharacterHit:
    name: str
    summary: str = ""                                   # 소개 첫 문단
    url: str = ""                                       # 출처 — 사람이 검수할 주소
    fields: dict[str, str] = field(default_factory=dict)      # 성별·나이·직업·경력·가족
    infobox: dict[str, str] = field(default_factory=dict)     # 딴 것 전부
    image_url: str = ""
    image_licence: str = ""
    ambiguous: bool = False                             # 후보가 여럿


def lookup(wiki: str, name: str, work_title: str = "", timeout: int = 20,
           with_image: bool = True) -> CharacterHit | None:
    """인물 문서를 읽어 온다. 못 찾으면 `None`.

    `work_title`은 위키 안에서 헷갈릴 때만 검색어에 붙는다. **대사는 절대 붙지 않는다.**
    """
    api = api_of(wiki)
    query = name if not work_title else f"{name} {work_title}"
    _SENT.append(query)

    try:
        found = _call(api, {"action": "query", "list": "search", "srsearch": query,
                            "srlimit": 3}, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    hits = ((found.get("query") or {}).get("search") or [])
    if not hits:
        return None

    # **이름이 정확히 같은 문서를 먼저 고른다.** 검색 순위에 맡기면 엉뚱한 인물이
    # 온다 — `Walter White`를 찾았는데 `Walter White Jr.`가 1위로 왔다(실측).
    # 아들·아버지처럼 이름이 겹치는 인물은 작품마다 있고, 그걸 잘못 집으면 성격과
    # 말투를 통째로 틀린 사람에게 붙인다.
    title = hits[0]["title"]
    lowered = name.strip().lower()
    for row in hits:
        if row["title"].strip().lower() == lowered:
            title = row["title"]
            break
    hit = CharacterHit(name=name, ambiguous=len(hits) > 1)

    try:
        page = _call(api, {"action": "parse", "page": title,
                           "prop": "wikitext|properties", "redirects": 1}, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return hit
    wikitext = (((page.get("parse") or {}).get("wikitext") or {}).get("*") or "")
    hit.infobox = parse_infobox(wikitext)
    hit.fields = pick_fields(hit.infobox)
    hit.summary = first_paragraph(wikitext)
    hit.url = f"{api[: -len('/api.php')]}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"

    if with_image:
        _fill_image(api, title, hit, timeout)
    return hit


def first_paragraph(wikitext: str, limit: int = 300) -> str:
    """소개 첫 문단. **인포박스와 틀을 걷어낸 뒤** 첫 줄을 딴다."""
    text = re.sub(r"\{\{[^{}]*\{\{.*?\}\}[^{}]*\}\}", "", wikitext, flags=re.S)
    while True:
        stripped = re.sub(r"\{\{[^{}]*\}\}", "", text, flags=re.S)
        if stripped == text:
            break
        text = stripped
    for line in text.split("\n"):
        line = _plain(line)
        if len(line) > 40 and not line.startswith(("=", "|", "*", "#", "[")):
            return line[:limit]
    return ""


def _fill_image(api: str, title: str, hit: CharacterHit, timeout: int) -> None:
    """대표 사진 주소와 **라이선스**를 채운다.

    라이선스를 함께 가져오는 것이 핵심이다. 주소만 있으면 작업자가 납품 문서에 넣어도
    되는지 판단할 수 없다.
    """
    try:
        page = _call(api, {"action": "query", "titles": title, "prop": "pageimages",
                           "piprop": "original", "redirects": 1}, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return
    pages = ((page.get("query") or {}).get("pages") or {})
    for row in pages.values():
        original = (row.get("original") or {}).get("source")
        if original:
            hit.image_url = original
            break
    if not hit.image_url:
        return
    # 파일 문서의 라이선스 정보. 못 찾으면 **비워 둔다** — "자유 이용"이라고 짐작하지 않는다.
    file_name = urllib.parse.unquote(hit.image_url.rsplit("/", 1)[-1].split("?")[0])
    try:
        info = _call(api, {"action": "query", "titles": f"File:{file_name}",
                           "prop": "imageinfo", "iiprop": "extmetadata"}, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return
    for row in ((info.get("query") or {}).get("pages") or {}).values():
        for item in row.get("imageinfo") or []:
            meta = item.get("extmetadata") or {}
            for key in ("LicenseShortName", "License", "UsageTerms"):
                value = (meta.get(key) or {}).get("value")
                if value:
                    hit.image_licence = _plain(str(value))
                    return
    # 팬덤 위키는 사진별 라이선스를 내주지 않는다. 그럴 때 **위키가 스스로 밝힌
    # 전체 라이선스**를 대신 읽는다 — 짐작이 아니라 위키의 선언이고, 사진별이 아니라는
    # 사실을 글자에 적어 둔다.
    site = _site_licence(api, timeout)
    if site:
        hit.image_licence = f"{site} (위키 전체 라이선스 — 사진별 표시가 없습니다)"


def _site_licence(api: str, timeout: int) -> str:
    try:
        info = _call(api, {"action": "query", "meta": "siteinfo",
                           "siprop": "rightsinfo"}, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return ""
    return _plain(str(((info.get("query") or {}).get("rightsinfo") or {}).get("text") or ""))
