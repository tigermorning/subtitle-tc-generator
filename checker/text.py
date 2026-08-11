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
