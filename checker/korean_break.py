"""한국어 줄바꿈 검사.

넷플릭스 공통 요건은 "문법 단위를 끊지 말고, 여러 선택지가 있으면 아래 줄이 더 긴
역피라미드로"다. 영어 쪽은 관사·전치사 목록으로 처리하지만 한국어는 그 목록이 다르다.

**형태소 분석기 없이 판정한다.** 여기서 보는 것은 의존명사·보조용언·관형사처럼
**닫힌 부류**라 목록이 유한하고, 목록에 없으면 조용히 넘어간다(오탐보다 누락을
택한다). 교정기의 형태소 자산을 끌어오면 더 정밀해지지만 그때는 kiwi 적재
비용(1~2분)이 따라온다 — 줄바꿈 하나 보자고 치를 값이 아니다.
"""

from __future__ import annotations

import re

from .text import count_chars, strip_tags

# 앞말에 기대어 쓰는 말. 줄 첫머리에 오면 앞 줄과 끊긴 것이다.
DEPENDENT_NOUNS = (
    "것", "거", "수", "줄", "리", "바", "터, ", "테", "때", "적", "만큼", "뿐", "듯",
    "채", "체", "척", "김", "탓", "덕분", "대로", "따름", "나름", "무렵", "즈음",
    "동안", "사이", "가운데", "중", "편", "지", "번", "개", "명", "마리", "권", "장",
)
# 보조 용언. 본용언과 갈라 놓으면 읽기가 끊긴다.
AUX_VERBS = (
    "하다", "하고", "해서", "해도", "한다", "합니다", "했다",
    "있다", "있는", "있어", "없다", "보다", "보고", "봐",
    "주다", "주고", "줘", "드리다", "드려", "버리다", "버렸",
    "가다", "오다", "지다", "싶다", "싶어", "말다", "놓다", "두다",
)
# 관형사. 뒤에 오는 명사와 갈라 놓으면 안 된다.
DETERMINERS = ("그", "이", "저", "어느", "무슨", "웬", "한", "두", "세", "네", "온", "각", "여러", "모든", "새", "옛")
# 관형형 어미로 끝나는 말 뒤에는 반드시 꾸밈받는 명사가 온다.
#
# 목적격·주격 조사(`를`·`을`·`은`)를 여기 넣었다가 실사용에서 오탐이 났다
# (`운전자를 / 추적 중입니다`는 조사 뒤에서 끊은 자연스러운 자리다). 조사 뒤는
# 끊어도 되는 자리이므로 뺐다. 남긴 것은 용언에서 온 관형형뿐이다.
#
# 2차 실측: `는`·`인`·`한`만으로는 조사·명사 어미와 갈리지 않았다
# (`차는`·`열쇠는`·`근처에는`·`범인`이 전부 관형형으로 잡혔다). 형태소 분석 없이
# 이 셋을 가르는 방법은 없다. **애매한 것은 버리고 용언에서 온 것이 분명한 형태만**
# 남긴다 — 놓치는 것은 사람이 보면 되지만, 오탐은 리포트를 못 쓰게 만든다.
ADNOMINAL_END = re.compile(r"(던|된|다는|라는|하는|되는|있는|없는|시킨|당한)$")


def _josa(word: str, with_batchim: str, without: str) -> str:
    """받침에 따라 조사를 고른다. 한국어 도구의 리포트에 조사 오류가 있으면
    지적의 신뢰가 깎인다."""
    if not word:
        return without
    last = word[-1]
    if "가" <= last <= "힣":
        return with_batchim if (ord(last) - 0xAC00) % 28 else without
    return without


def _first_word(line: str) -> str:
    words = strip_tags(line).strip().split()
    return words[0] if words else ""


def _last_word(line: str) -> str:
    words = strip_tags(line).strip().split()
    return words[-1] if words else ""


def check_line_break(lines: list[str], weights: dict | None = None) -> list[str]:
    """두 줄 자막의 줄바꿈 자리를 본다. 문제 문구 목록을 돌려준다."""
    if len(lines) != 2:
        return []

    upper, lower = lines
    if not upper.strip() or not lower.strip():
        return []

    problems: list[str] = []
    head = _first_word(lower)
    tail = _last_word(upper)

    # 2인 화자 자막은 줄마다 화자가 다르므로 문법 단위로 볼 수 없다.
    if strip_tags(lower).lstrip().startswith("-"):
        return []

    # 의존명사는 **앞에 꾸미는 말이 반드시 있다**. 윗줄이 그런 말로 끝날 때만
    # 의존명사로 본다 — 그러지 않으면 인명 `척 파머`의 `척`을 의존명사로 오인한다
    # (실사용 자막에서 실제로 났다).
    upper_modifies = bool(ADNOMINAL_END.search(tail)) or tail in DETERMINERS
    if upper_modifies and head.startswith(DEPENDENT_NOUNS):
        problems.append(
            f"아랫줄이 의존명사 '{head}'{_josa(head, '으로', '로')} 시작합니다"
            " — 앞말과 붙는 말입니다")
    elif head.startswith(AUX_VERBS):
        problems.append(
            f"아랫줄이 보조 용언 '{head}'{_josa(head, '으로', '로')} 시작합니다"
            " — 본용언과 갈렸습니다")

    if False:
        pass
    elif tail in DETERMINERS:
        problems.append(
            f"윗줄이 관형사 '{tail}'{_josa(tail, '으로', '로')} 끝납니다"
            " — 꾸밈받는 말과 갈렸습니다")
    elif ADNOMINAL_END.search(tail) and len(tail) > 1 and not problems:
        # 관형형 어미는 뒤에 명사를 데려온다. 다만 종결형과 겹치는 형태가 많아
        # (`먹는다`·`간다`) 확정하지 않고 확인만 구한다.
        problems.append(
            f"윗줄이 '{tail}'{_josa(tail, '으로', '로')} 끝나"
            " 꾸밈받는 말과 갈렸을 수 있습니다")

    return problems


def check_top_heavy(lines: list[str], weights: dict | None = None) -> list[str]:
    """역피라미드 권고. **위반이 아니다.**

    넷플릭스 문구는 "여러 선택지가 있으면 아래 줄이 더 긴 형태로"다. 다른 자리에서
    끊을 수 있었는지는 기계가 알 수 없으므로, 확실히 기울어진 것만 말한다. 임계를
    1.6배로 잡았더니 실사용 자막에서 64건이 나와 리포트가 그것으로 덮였다 — 2배로
    올리고 규칙도 따로 뺐다.
    """
    if len(lines) != 2:
        return []
    if strip_tags(lines[1]).lstrip().startswith("-"):
        return []
    upper_len = count_chars(lines[0], weights)
    lower_len = count_chars(lines[1], weights)
    if lower_len > 0 and upper_len >= lower_len * 2:
        return [f"윗줄({upper_len:g}자)이 아랫줄({lower_len:g}자)의 2배 이상입니다"
                " — 다른 자리에서 끊을 수 있는지 보세요"]
    return []


# --- 줄바꿈을 **만든다** (2026-09-13) ---------------------------------------
# 위 두 함수는 이미 나뉜 두 줄을 **보기만** 했다. 생성 경로에는 줄을 나누는
# 단계가 아예 없었다 — 드라마B E02 초안 846개 중 두 줄이 **0개**였고 한 줄이
# 63자까지 갔다(정답은 961개 중 287개가 두 줄, 최대 36자). 우리 검사기로
# 우리 초안을 보면 그 자리가 규정 위반으로 잡힌다(디즈니 스펙 182건).
#
# 정답과 견주면 이 빈칸이 **분할 단위**까지 흔든다(2026-09-13 실측):
#
#     우리가 쪼갠 자리   정답 글자수 중앙 18~19자, 그중 51~56%가 두 줄
#     우리가 합친 자리   정답 두 자막 사이 간격 중앙 84ms(전체 917ms)
#
# 정답은 소리가 안 끊겨도 글자 수 때문에 두 자막으로 나누고, 대신 18~19자를
# 두 줄로 한 자막에 담는다. 두 줄을 못 만들면 그 둘 다 못 흉내 낸다.
#
# **새 상수를 만들지 않는다.** 후보 자리를 전부 놓고 위 검사 함수를 심판으로
# 써서 고른다 — 규정이 이미 말한 것(문법 단위를 끊지 말 것, 역피라미드)이
# 그대로 목적함수가 된다.
_OVER_LIMIT = 100.0      # 한 줄 한계를 넘는 글자당 벌점 — 가장 무겁다
_BROKEN_UNIT = 40.0      # 문법 단위를 끊었을 때(check_line_break)
_TOP_HEAVY = 10.0        # 윗줄이 아랫줄의 2배 이상(check_top_heavy)
_UPPER_LONGER = 0.5      # 역피라미드에서 벗어난 글자당


def _penalty(upper: str, lower: str, per_line: float, weights: dict | None) -> float:
    upper_len = count_chars(upper, weights)
    lower_len = count_chars(lower, weights)
    score = _OVER_LIMIT * (max(0.0, upper_len - per_line) + max(0.0, lower_len - per_line))
    score += _BROKEN_UNIT * len(check_line_break([upper, lower], weights))
    score += _TOP_HEAVY * len(check_top_heavy([upper, lower], weights))
    if upper_len > lower_len:
        score += _UPPER_LONGER * (upper_len - lower_len)
    return score


def place_line_break(text: str, per_line: float, weights: dict | None = None) -> str:
    """한 줄짜리 자막 텍스트를 규정 한 줄 한계에 맞춰 두 줄로 나눈다.

    - 이미 줄이 나뉘어 있으면 **건드리지 않는다**(앞 단계의 판단을 덮지 않는다).
    - 한 줄에 들어가면 그대로 둔다.
    - 나눌 자리는 띄어쓰기 자리뿐이다. 단어 중간에서 끊지 않는다.
    - 2인 화자 자막(`- `로 시작하는 두 대사)은 두 번째 대시 앞에서 끊는다.
    - 어디서 끊어도 한계를 못 지키면 **가장 덜 나쁜 자리**로 나눈다 — 줄바꿈이
      해결할 수 없는 문제(글자가 너무 많다)는 검사가 사람에게 알린다(규칙 3).
    """
    if not text or "\n" in text or not per_line:
        return text
    if count_chars(text, weights) <= per_line:
        return text

    stripped = text.strip()
    words = stripped.split(" ")
    if len(words) < 2:
        return text

    # 2인 화자: 두 번째 대시가 아랫줄 첫 글자가 되도록
    dash_at = [i for i, word in enumerate(words) if i and word.startswith("-")]
    candidates = dash_at[:1] if dash_at and stripped.startswith("-") else range(1, len(words))

    best, best_score = None, None
    for i in candidates:
        upper = " ".join(words[:i])
        lower = " ".join(words[i:])
        if not upper.strip() or not lower.strip():
            continue
        score = _penalty(upper, lower, per_line, weights)
        if best_score is None or score < best_score:
            best, best_score = (upper, lower), score
    if best is None:
        return text
    return best[0] + "\n" + best[1]
