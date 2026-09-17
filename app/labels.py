"""검사 결과에 사람에게 보이는 이름을 붙인다.

**규칙 번호를 화면에 내지 않는다**(사용자 결정 2026-09-17). 이 도구를 쓰는 사람은
번역·SDH 작업자다 — `T05`·`S02`·`K01`이 무엇인지 모르고, 알 필요도 없다. 번호로는
무엇이 걸렸는지 알 수 없으니 표를 보고도 규정 파일을 다시 뒤져야 한다. 그래서
**무엇을 보는 검사인지**(규칙의 `message`)를 이름으로 쓴다.

번호는 버리지 않는다. 도구설명에 남겨 두면 개발자가 어느 규칙인지 찾을 수 있다.

**화면에서 떼어 놓는다.** Qt를 모르는 함수라 PySide6 없이도 시험한다.
"""

from __future__ import annotations

import re

# `T05`·`TC00`·`K01` 꼴. 사람이 읽는 이름이 아니다.
_RULE_ID = re.compile(r"^[A-Z]{1,3}\d{1,3}$")

# 용어 조사(`checker.terms.Term.kind`)가 붙이는 갈래. 영어 낱말도 작업자에게는 번호와 같다.
TERM_KINDS = {
    "person": "인물",
    "place": "지명",
    "acronym": "약어",
    "technical": "전문 용어",
    "unknown": "갈래 모름",
}


def check_name(violation: dict) -> str:
    """무엇을 보는 검사인가. 규칙 문구가 없으면 붙어 온 이름을 쓰되 번호는 내지 않는다."""
    message = str(violation.get("message") or "").strip()
    if message:
        return message
    name = str(violation.get("rule_id") or "").strip()
    if name in TERM_KINDS:
        return TERM_KINDS[name]
    if not name or _RULE_ID.match(name):
        return "기타 지적"
    return name


def check_label(violation: dict) -> str:
    """검사 결과 표의 `검사` 칸. 예: `번역 자막은 마침표를 쓰지 않고… · 자동`."""
    mark = "자동" if violation.get("auto_fixable") else "확인"
    return f"{check_name(violation)} · {mark}"


def check_detail(violation: dict) -> str:
    """`내용` 칸. 이름 칸에 이미 규칙 문구가 있으니 같은 말을 되풀이하지 않는다."""
    detail = str(violation.get("detail") or "").strip()
    if detail:
        return detail
    return str(violation.get("text") or "").strip()


def check_tooltip(violation: dict) -> str:
    """개발자가 어느 규칙인지 찾을 수 있게 번호와 조항을 남긴다."""
    parts = [str(violation.get("rule_id") or ""), str(violation.get("clause") or "")]
    return " · ".join(p for p in parts if p)
