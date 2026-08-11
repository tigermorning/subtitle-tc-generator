"""자동 교정. 규칙에 `auto: true`가 붙었고 **여기 고치는 함수가 등록된 것만** 고친다.

프로파일이 `auto: true`라고 말해도 기계적으로 고칠 수 없는 자리가 있다(대괄호
미닫힘은 어디를 닫아야 하는지 사람만 안다). 그런 규칙은 고치지 않고 남긴 뒤
"자동 표시지만 고치지 못한 것"으로 보고한다 — 고쳤다고 말하지 않는 것이 중요하다.

교정은 항상 새 파일로 나간다. 원본을 덮어쓰지 않는다.
"""

from __future__ import annotations

import re

from .model import Event

FIXERS: dict[str, callable] = {}


def fixer(name: str):
    def deco(fn):
        FIXERS[name] = fn
        return fn

    return deco


@fixer("three_dot_ellipsis")
def _fix_ellipsis(text: str, ctx: dict) -> str:
    return re.sub(r"\.{3,}", "…", text)


@fixer("double_space")
def _fix_double_space(text: str, ctx: dict) -> str:
    return "\n".join(re.sub(r" {2,}", " ", line) for line in text.split("\n"))


@fixer("italics_present")
def _fix_italics(text: str, ctx: dict) -> str:
    return re.sub(r"</?i>|\{\\i[01]\}", "", text, flags=re.IGNORECASE)


@fixer("line_end_period_or_comma")
def _fix_line_end(text: str, ctx: dict) -> str:
    out = []
    for line in text.split("\n"):
        stripped = line.rstrip()
        if stripped.endswith((".", ",")) and not stripped.endswith("..."):
            stripped = stripped[:-1].rstrip()
        out.append(stripped)
    return "\n".join(out)


@fixer("acronym_with_periods")
def _fix_acronym(text: str, ctx: dict) -> str:
    return re.sub(r"\b((?:[A-Za-z]\.){2,})", lambda m: m.group(1).replace(".", ""), text)


@fixer("music_note_spacing")
def _fix_note_spacing(text: str, ctx: dict) -> str:
    note = (ctx["profile"].get("music") or {}).get("music_note")
    if not note:
        return text
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith(note):
            s = note + " " + s[len(note) :].lstrip()
        if s.endswith(note):
            s = s[: -len(note)].rstrip() + " " + note
        out.append(s)
    return "\n".join(out)


@fixer("dual_speaker_marker_format")
def _fix_dual_speaker(text: str, ctx: dict) -> str:
    """한국어는 하이픈+공백, 영어는 공백 없는 하이픈. 프로파일이 정한 쪽으로 맞춘다."""
    marker = (ctx["profile"].get("dual_speaker") or {}).get("marker")
    if not marker:
        return text
    wants_space = marker.endswith(" ")
    out = []
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith("-") and not s.startswith("--"):
            body = s[1:].lstrip()
            s = ("- " if wants_space else "-") + body
        out.append(s)
    return "\n".join(out)


@fixer("lyric_line_not_capitalized")
def _fix_lyric_caps(text: str, ctx: dict) -> str:
    music = ctx["profile"].get("music") or {}
    note = music.get("music_note") or "♪"
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith(note):
            body = s[len(note) :].lstrip()
            if body[:1].isalpha() and body[:1].islower():
                body = body[0].upper() + body[1:]
                s = f"{note} {body}"
        out.append(s)
    return "\n".join(out)


# --- 문서 단위 교정 -------------------------------------------------------
#
# 글자만 봐서는 못 고치는 것들. 자막 위치는 **다른 자막과의 관계**로 정해지므로
# 한 줄씩 넘겨서는 판단할 수 없다.
#   fn(events, ctx) -> 고친 개수

DOC_FIXERS: dict[str, callable] = {}


def doc_fixer(name: str):
    def deco(fn):
        DOC_FIXERS[name] = fn
        return fn

    return deco


@doc_fixer("position_collides_with_forced_narrative")
def _fix_position(events: list[Event], ctx: dict) -> int:
    """화면자막과 겹치는 말자막을 상단 중앙으로. 겹칠 것이 없으면 되돌린다.

    영상에서 추정한 근거(`certain=False`)로는 고치지 않는다 — 무늬를 글자로 잘못
    본 것일 수 있고, 그렇게 올라간 자막은 사람이 원인을 못 찾는다.
    """
    from .position import apply_positions, suggest_positions

    suggestions = suggest_positions(events, ctx.get("profile"), ctx.get("busy_spans"),
                                    ctx.get("job_rules"))
    return apply_positions(events, suggestions, only_certain=True)


def apply_fixes(events: list[Event], profile: dict, job_rules=None) -> tuple[list[Event], list[str], list[str]]:
    """`auto: true` 규칙 중 고칠 수 있는 것을 적용한다.

    반환: (고친 이벤트, 적용한 검사 이름, 자동 표시지만 못 고친 검사 이름)
    """
    ctx = {"profile": profile, "job_rules": job_rules}
    applied: list[str] = []
    unfixable: list[str] = []

    names: list[str] = []
    for rule in profile.get("rules", []):
        if not rule.get("auto"):
            continue
        checks = rule["check"]
        for name in checks if isinstance(checks, list) else [checks]:
            if name in DOC_FIXERS:
                continue
            if name in FIXERS:
                if name not in names:
                    names.append(name)
            else:
                label = f"{rule['id']} ({name})"
                if label not in unfixable:
                    unfixable.append(label)

    # 문서 단위 교정을 먼저 돌린다. 위치 태그가 붙고 난 뒤에 글자 교정이 와야
    # 태그를 글자로 착각하지 않는다.
    staged = [Event(ev.index, ev.start_ms, ev.end_ms, ev.text) for ev in events]
    for rule in profile.get("rules", []):
        if not rule.get("auto"):
            continue
        checks = rule["check"]
        for name in checks if isinstance(checks, list) else [checks]:
            fn = DOC_FIXERS.get(name)
            if fn is not None and fn(staged, ctx) and name not in applied:
                applied.append(name)
    events = staged

    fixed = []
    for ev in events:
        text = ev.text
        for name in names:
            new_text = FIXERS[name](text, ctx)
            if new_text != text:
                if name not in applied:
                    applied.append(name)
                text = new_text
        fixed.append(Event(ev.index, ev.start_ms, ev.end_ms, text))

    return fixed, applied, unfixable


@fixer("ellipsis_style_mismatch")
def _fix_ellipsis_style(text: str, ctx: dict) -> str:
    """말줄임표를 **프로파일이 정한 쪽으로** 맞춘다.

    방향이 플랫폼마다 반대라 한쪽으로 굳혀 두면 다른 쪽에서 틀린다
    (넷플릭스 전각, 쿠팡 점 셋).
    """
    want = (ctx["profile"].get("text") or {}).get("ellipsis_char")
    if want == "…":
        return re.sub(r"\.{3,}", "…", text)
    if want == "...":
        return text.replace("…", "...")
    return text
