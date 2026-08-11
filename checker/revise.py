"""1차 번역을 다시 본다 — 작업자가 하는 2차·3차 작업.

작업자 자료(`작업 기본 원칙` 569~579행)가 단계를 이렇게 나눈다.

    1차   오역 없이 빠르게. 맥락 생각 말고            (`translate.py`가 하는 일)
    2차   올바른 한국어로. **전문 용어 조사**, 맥락 안에서 문장의 역할 바로잡기
    3차   영상 없이 줄글로 읽으며 말투·흐름 윤문

    (ex.) 1차 그들과 싸우기 전에 그들을 발견해야 한다
          2차 놈들과 싸우기 전에 우선 찾아야 한다
          3차 우선 찾아야 싸우든 말든 하지

**한 번에 다 시키지 않는 이유가 여기 있다.** 사람도 나눠서 한다. 한 번에 "잘
번역해라"라고 하면 모델은 세 가지를 뒤섞어 어중간하게 낸다. 1차는 정확도, 2차는
용어와 맥락, 3차는 말맛 — 볼 것이 다르다.

**바꾼 것은 전부 남긴다.** 2차가 1차보다 늘 나은 것은 아니다. 무엇을 왜 바꿨는지
보여야 사람이 되돌릴 수 있다.

이 단계는 로컬 모델로 돈다. 대본이 밖으로 나가지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Event
from .translate import _parse_numbered

SECOND_PASS = (
    "당신은 영상 번역 감수자입니다. 1차 번역을 **2차 번역**으로 다듬습니다.\n"
    "볼 것은 셋뿐입니다.\n"
    "  1. 오역 — 원문의 뜻과 다른 것\n"
    "  2. 용어 — 주어진 고정 표기를 쓰지 않은 것\n"
    "  3. 맥락 — 앞뒤 자막과 이어지지 않거나 지시 대상이 틀린 것\n"
    "\n"
    "규칙:\n"
    "- 마침표를 쓰지 않습니다. 문장 끝 쉼표도 쓰지 않습니다.\n"
    "- 인칭대명사('그', '그녀', '그들')를 쓰지 않습니다.\n"
    "- 문장 요소를 덜어냅니다: '수', '있', '것', 보조 용언, 극존칭 '-시-'.\n"
    "- 말투(존댓말/반말)는 1차를 따릅니다. 흔들지 마세요.\n"
    "- **고칠 곳이 없으면 1차를 그대로 씁니다.** 바꾸기 위해 바꾸지 마세요.\n"
    "- 번호를 그대로 붙여 같은 개수로 냅니다. 설명하지 마세요."
)

THIRD_PASS = (
    "당신은 영상 번역가입니다. 자막을 소리 내어 읽으며 **말맛만** 다듬습니다.\n"
    "- 뜻을 바꾸지 마세요. 용어를 바꾸지 마세요.\n"
    "- 주어와 서술어가 호응하는지, 입에 붙는지만 봅니다.\n"
    "- 자막은 짧을수록 좋습니다. 늘리지 마세요.\n"
    "- 고칠 곳이 없으면 그대로 씁니다.\n"
    "- 번호를 그대로 붙여 같은 개수로 냅니다. 설명하지 마세요."
)


@dataclass
class Revision:
    index: int
    before: str
    after: str
    stage: str          # 2차 | 3차

    @property
    def changed(self) -> bool:
        return self.before.strip() != self.after.strip()


def revise(events: list[Event], translator, source: dict[int, str] | None = None,
           glossary=None, stage: str = "2차", batch: int = 8, context: int = 2,
           progress=None) -> tuple[list[Event], list[Revision]]:
    """자막을 다시 본다. (고친 자막, 바뀐 내역)

    `source`는 자막 번호별 원문이다. 2차에서는 원문이 있어야 오역을 볼 수 있다 —
    없으면 한국어만 보고 다듬는 3차처럼 돈다.
    """
    say = progress or (lambda _m: None)
    system = SECOND_PASS if stage == "2차" else THIRD_PASS
    source = source or {}
    revisions: list[Revision] = []
    out: list[Event] = []

    for start in range(0, len(events), batch):
        chunk = events[start:start + batch]
        say(f"{stage} {start + 1}~{start + len(chunk)} / {len(events)}")

        before = ""
        if context and start:
            recent = events[max(0, start - context):start]
            before = ("앞 자막(참고만 하세요):\n"
                      + "\n".join(f"  {e.text}" for e in recent) + "\n\n")

        lines = []
        for event in chunk:
            original = source.get(event.index)
            if original and stage == "2차":
                lines.append(f"{event.index}. [원문] {original}\n   [1차] {event.text}")
            else:
                lines.append(f"{event.index}. {event.text}")

        prompt = (f"{before}{glossary.hint() if glossary else ''}\n"
                  f"다음 자막을 {stage} 번역으로 다듬으세요.\n\n" + "\n".join(lines))
        reply = translator.ask(system, prompt)
        got = _parse_numbered(reply, [e.index for e in chunk])

        for event in chunk:
            text = (got.get(event.index) or "").strip()
            # 모델이 형식을 흘리면(`[2차]` 같은 표지) 걷어낸다.
            text = re.sub(r"^\[[^\]]{1,6}\]\s*", "", text)
            if not text or _too_different(event.text, text):
                # **의심스러우면 1차를 지킨다.** 2차가 늘 나은 것은 아니다.
                out.append(Event(event.index, event.start_ms, event.end_ms, event.text))
                continue
            out.append(Event(event.index, event.start_ms, event.end_ms, text))
            revision = Revision(event.index, event.text, text, stage)
            if revision.changed:
                revisions.append(revision)

    return out, revisions


def _too_different(before: str, after: str, limit: float = 1.5) -> bool:
    """길이가 너무 달라지면 다듬은 것이 아니라 다시 쓴 것이다.

    모델이 설명을 덧붙이거나 두 자막을 합쳐 버리는 사고를 막는다.

    한계를 1.5배로 둔다. 2.5배 -> 1.8배로 조였다가 1.77배짜리 덧붙임을 또
    통과시켰다 —
    **한국어를 한국어로 다듬는 단계**라 길이가 크게 늘 이유가 없다(원어에서 옮기는
    1차와 다르다). 자막은 화면에 맞춰 길이가 정해져 있어 조금만 늘어도 못 쓴다.
    실제 다듬기는 1.2~1.3배를 넘지 않았다(`진짜야?` -> `진심이야?` 1.25배).
    """
    if not before.strip():
        return False
    ratio = len(after) / max(len(before), 1)
    return ratio > limit or ratio < 1 / limit


def report(revisions: list[Revision], show: int = 20) -> str:
    """무엇을 왜 바꿨는지. 사람이 되돌릴 수 있어야 한다."""
    if not revisions:
        return "바꾼 자막이 없습니다."
    lines = [f"{revisions[0].stage}에서 {len(revisions)}개를 고쳤습니다"]
    for revision in revisions[:show]:
        lines.append(f"  #{revision.index}")
        lines.append(f"    전: {revision.before}")
        lines.append(f"    후: {revision.after}")
    if len(revisions) > show:
        lines.append(f"  … 외 {len(revisions) - show}개")
    return "\n".join(lines)
