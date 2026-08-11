"""자막을 보고 어느 플랫폼 작업물인지 유추한다.

**왜 필요한가**: 프로파일을 잘못 고르면 지적이 통째로 뒤집힌다. 쿠팡 작업물에
넷플릭스 프로파일을 걸면 "점 셋을 …로 바꾸세요"라고 하는데, 쿠팡에서는 점 셋이
정답이다. 사람이 아이콘 하나 잘못 누른 것을 기계가 알아채야 한다.

**유추 근거**: OTT마다 화자명·어조·음악·삐 처리 표기가 다르다.

    쿠팡      (철수)          소괄호 화자명
    넷플릭스   [철수/작게]      슬래시로 나눈 대괄호
    디즈니     [철수가 작게]    서술형 대괄호, [♪ 음악], O 삐 처리

**확정하지 않는다.** 근거가 약하면 말하지 않고, 강해도 "프로파일을 확인하라"고만
한다. 자막이 짧거나 화자명이 없으면 아무 말도 못 하는 것이 정상이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Event
from .text import strip_tags

SPEAKER_HEAD = re.compile(r"^\s*-?\s*([\[(])([^\])]+)([\])])\s*(\S.*)$")


@dataclass
class PlatformGuess:
    platform: str
    score: int
    evidence: list[str] = field(default_factory=list)


def detect_platform(events: list[Event]) -> list[PlatformGuess]:
    """점수가 높은 순으로 돌려준다. 근거가 없으면 빈 목록."""
    scores = {"netflix": 0, "disney": 0, "coupang": 0}
    evidence: dict[str, list[str]] = {k: [] for k in scores}

    def add(platform: str, points: int, why: str) -> None:
        scores[platform] += points
        if why not in evidence[platform]:
            evidence[platform].append(why)

    for ev in events:
        text = strip_tags(ev.text)

        for line in text.split("\n"):
            m = SPEAKER_HEAD.match(line)
            if m:
                opener, inner, _closer, _rest = m.groups()
                if opener == "(":
                    add("coupang", 3, f"소괄호 화자명 ({inner})")
                elif "/" in inner:
                    add("netflix", 3, f"슬래시로 나눈 화자명 [{inner}]")
                elif re.search(r"(이|가)\s+\S+(로|게)$", inner):
                    add("disney", 3, f"서술형 화자명 [{inner}]")

        for inner in re.findall(r"\[([^\]]*)\]", text):
            if "♪" in inner and any(k in inner for k in ("음악", "곡", "연주")):
                add("disney", 3, f"음악 효과음 안의 음표 [{inner}]")
            elif any(k in inner for k in ("음악", "곡", "연주")) and "♪" not in inner:
                add("netflix", 1, f"음표 없는 음악 효과음 [{inner}]")
                add("coupang", 1, f"음표 없는 음악 효과음 [{inner}]")

        if "음 소거" in text:
            add("disney", 2, "[음 소거 효과음]")
            add("coupang", 2, "[음 소거 효과음]")
        if re.search(r"O+(?=[가-힣])|(?<=[가-힣])O+", text):
            add("disney", 2, "대문자 O 삐 처리")
        if re.search(r"\*+(?=[가-힣])|(?<=[가-힣])\*+", text):
            add("netflix", 1, "별표 삐 처리")
            add("coupang", 1, "별표 삐 처리")

        if "…" in text:
            add("netflix", 1, "전각 말줄임표")
            add("disney", 1, "전각 말줄임표")
        if "..." in text:
            add("coupang", 1, "점 셋 말줄임표")
            add("disney", 1, "점 셋 말줄임표")

    guesses = [PlatformGuess(p, s, evidence[p]) for p, s in scores.items() if s]
    guesses.sort(key=lambda g: -g.score)
    return guesses


def mismatch_warning(events: list[Event], profile: dict, margin: int = 4) -> str | None:
    """고른 프로파일과 자막의 표기가 어긋나면 경고 문구를 돌려준다.

    `margin`보다 확실히 앞설 때만 말한다 — 애매한 근거로 사람을 흔들면 오히려
    프로파일을 잘못 바꾸게 된다.
    """
    guesses = detect_platform(events)
    if not guesses:
        return None

    chosen = profile.get("platform")
    top = guesses[0]
    if top.platform == chosen:
        return None

    runner_up = next((g.score for g in guesses if g.platform == chosen), 0)
    if top.score - runner_up < margin:
        return None

    return (f"자막 표기는 {top.platform} 쪽으로 보이는데 {chosen} 프로파일로 검사했습니다. "
            f"근거: {', '.join(top.evidence[:3])}. 프로파일을 확인하세요.")
