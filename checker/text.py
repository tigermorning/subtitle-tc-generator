"""글자 수·읽기 속도 계산.

넷플릭스 한국어는 CJK 1자, 그 외(라틴 문자·공백·문장부호) 0.5자로 센다.
영어는 전부 1자다. 이 가중치는 프로파일의 `limits.char_weights`가 정한다 —
코드에 박지 않는다.
"""

from __future__ import annotations

import re

TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")  # <i>, {\an8} 등

# CJK로 세는 유니코드 블록. SubtitleEdit의 CalcCjk와 같은 범위를 쓴다.
_CJK_RANGES = (
    (0x1100, 0x11FF),  # 한글 자모
    (0x2E80, 0x2EFF),  # CJK 부수
    (0x3000, 0x303F),  # CJK 기호·문장부호
    (0x3040, 0x309F),  # 히라가나
    (0x30A0, 0x30FF),  # 가타카나
    (0x3200, 0x32FF),
    (0x3300, 0x33FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),  # CJK 통합 한자
    (0xAC00, 0xD7AF),  # 한글 음절
    (0xFE30, 0xFE4F),
)


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


# 한글만 골라내는 범위. `_CJK_RANGES`는 글자 수 계산용(한글도 CJK로 1자 취급)이라
# 언어 판정에는 못 쓴다 — 일본어 가나·한자도 같이 걸린다.
_HANGUL_RANGES = (
    (0x1100, 0x11FF),  # 한글 자모
    (0x3130, 0x318F),  # 한글 호환 자모
    (0xA960, 0xA97F),  # 한글 자모 확장-A
    (0xAC00, 0xD7A3),  # 한글 음절
    (0xD7B0, 0xD7FF),  # 한글 자모 확장-B
)


def is_hangul(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _HANGUL_RANGES)


def has_hangul(text: str) -> bool:
    return any(is_hangul(ch) for ch in strip_tags(text))


def is_foreign_language_text(text: str) -> bool:
    """대사가 한글 없이 다른 문자 체계(가나·한자·라틴 등)로만 됐으면 참이다.

    화면 효과음(`[한숨]`)이나 숫자만 있는 자막은 언어 판정 대상이 아니다 — 글자
    (`str.isalpha()`)가 하나도 없으면 거짓을 돌려준다.
    """
    stripped = strip_tags(text)
    if has_hangul(stripped):
        return False
    return any(ch.isalpha() for ch in stripped)


def strip_tags(text: str) -> str:
    return TAG_RE.sub("", text)


def count_chars(text: str, weights: dict | None = None) -> float:
    """가중치를 적용한 글자 수. 태그는 세지 않는다."""
    cjk_w = float((weights or {}).get("cjk", 1.0))
    other_w = float((weights or {}).get("other", 1.0))
    total = 0.0
    for ch in strip_tags(text):
        if ch in ("\n", "\r"):
            continue
        total += cjk_w if is_cjk(ch) else other_w
    return total


def chars_per_second(text: str, duration_ms: int, weights: dict | None = None) -> float:
    if duration_ms <= 0:
        return float("inf")
    return count_chars(text, weights) / (duration_ms / 1000.0)
