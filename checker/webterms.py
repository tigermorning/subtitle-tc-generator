"""용어의 한국어 표기를 밖에서 찾아온다 — **낱말만 내보낸다.**

국립국어원 외래어 용례는 권위 있지만 좁다. 실제 작업에서 걸리는 것들 — `Bastogne`,
`Malayan tiger`, `82nd Airborne Division` — 이 거기 없다. 작업자가 인터넷을 뒤지는
이유가 그것이다.

**그런데 아무거나 검색하면 안 된다.** 미공개 작품의 대사를 검색창에 넣는 순간 계약
위반이다. 그래서 이 모듈은 두 가지를 지킨다.

    ① **낱말 하나만 보낸다.** 대사·문맥·파일 이름은 절대 나가지 않는다.
    ② **기본은 꺼져 있다.** 부르는 쪽이 명시적으로 켜야 돈다(`--web`).

`Bastogne` 같은 지명은 그 자체로는 작품을 알려 주지 않는다. 하지만 등장인물의 흔치
않은 이름이라면 이야기가 다르다 — 그 판단은 사람이 한다. 무엇을 내보냈는지 전부
기록으로 남긴다.

**위키백과 언어 링크를 쓴다.** 영어 표제어에 걸린 한국어 표제어를 그대로 가져오는
방식이라, 검색 결과를 짐작하는 것이 아니라 **문서 대 문서의 대응**을 읽는다. 출처
주소가 함께 나오므로 작업자가 검수할 수 있다("NOTE 란에 출처 표기" — 작업자 자료).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

API = "https://en.wikipedia.org/w/api.php"
# 위키미디어는 정체를 밝히지 않는 요청을 막는다(403). 무엇이 부르는지 밝힌다.
USER_AGENT = "subtitle-editor/0.1 (local subtitle tool; https://github.com/tigermorning/subtitle-editor)"


@dataclass
class WebHit:
    korean: str
    english: str
    url: str
    ambiguous: bool = False      # 같은 이름의 문서가 여럿이라 갈라 놓은 것

    @property
    def note(self) -> str:
        mark = " / 같은 이름 여럿 — 확인 필요" if self.ambiguous else ""
        return f"위키백과: {self.url}{mark}"


def _call(params: dict, timeout: int = 20) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json"})
    request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


# 괄호가 붙은 표제어는 **같은 이름이 여럿이라 갈라 놓은 문서**다(`불 (드라마)`,
# `니스 (프랑스)`). 어느 쪽이 맞는지는 작품 문맥을 봐야 하므로 기계가 정하지 않는다.
DISAMBIGUATED = re.compile(r"\s*\([^)]*\)\s*$")


def korean_title(term: str, timeout: int = 20, search: bool = False) -> WebHit | None:
    """영어 표제어에 걸린 한국어 표제어. 없으면 None.

    **넘기는 것은 `term` 문자열뿐이다.**

    **검색은 기본으로 쓰지 않는다.** 처음에는 표제어가 안 맞을 때 검색으로 한 번 더
    봤는데, 그러면 자신 있게 틀린다 — `Jason Bull`(인물)이 `불 (드라마)`가 되고
    `Your Honor`가 푸 파이터스 앨범 `In Your Honor`가 됐다(2026-08-11 실측).
    문서 대 문서로 정확히 대응할 때만 답하고, 나머지는 사람에게 넘긴다.
    """
    hit = _langlink(term, timeout)
    if hit or not search:
        return hit

    try:
        found = _call({"action": "query", "list": "search", "srsearch": term,
                       "srlimit": 1}, timeout)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    results = (found.get("query") or {}).get("search") or []
    if not results:
        return None
    best = results[0].get("title", "")
    # 검색이 엉뚱한 문서를 집을 수 있다. 낱말이 제목에 남아 있을 때만 믿는다.
    if best and term.split()[0].lower() in best.lower():
        return _langlink(best, timeout)
    return None


def _langlink(title: str, timeout: int) -> WebHit | None:
    try:
        data = _call({"action": "query", "titles": title, "prop": "langlinks",
                      "lllang": "ko", "redirects": 1}, timeout)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        for link in page.get("langlinks") or []:
            korean = link.get("*") or ""
            if korean:
                english = page.get("title", title)
                # 갈라 놓은 문서면 어느 쪽인지 사람이 정해야 한다.
                if DISAMBIGUATED.search(korean):
                    return WebHit(DISAMBIGUATED.sub("", korean), english,
                                  "https://ko.wikipedia.org/wiki/"
                                  + urllib.parse.quote(korean.replace(" ", "_")),
                                  ambiguous=True)
                return WebHit(korean, english,
                              "https://ko.wikipedia.org/wiki/"
                              + urllib.parse.quote(korean.replace(" ", "_")))
    return None


def lookup(terms: list[str], timeout: int = 20, progress=None) -> dict[str, WebHit]:
    """여러 낱말을 찾는다. 무엇을 내보냈는지 알리며 진행한다."""
    say = progress or (lambda _m: None)
    found: dict[str, WebHit] = {}
    for term in terms:
        say(f"찾는 중: {term}")
        hit = korean_title(term, timeout)
        if hit:
            found[term] = hit
    return found
