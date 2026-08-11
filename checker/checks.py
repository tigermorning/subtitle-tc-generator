"""검사 구현. 어떤 검사를 돌릴지는 코드가 아니라 **프로파일이 정한다**.

프로파일의 `rules[].check` 이름으로 여기 등록된 함수를 찾는다. 없으면 조용히
건너뛰지 않고 리포트의 `unimplemented_checks`에 남긴다 — 검사하지 않은 것을
"통과"로 보이게 하지 않는다.

검사 함수 계약:
    fn(event, ctx) -> list[tuple[line_no | None, detail]]
빈 리스트면 위반 없음. `detail`은 사람이 볼 근거 문구다.
"""

from __future__ import annotations

import re

from .model import Event
from .text import count_chars, chars_per_second, strip_tags

REGISTRY: dict[str, callable] = {}


def check(name: str):
    def deco(fn):
        REGISTRY[name] = fn
        return fn

    return deco


# --- 수치 ---------------------------------------------------------------


@check("duration_out_of_range")
def _duration(ev: Event, ctx: dict):
    rng = (ctx["limits"].get("duration_ms") or {})
    lo, hi = rng.get("min"), rng.get("max")
    if lo is not None and ev.duration_ms < lo:
        return [(None, f"{ev.duration_ms}ms — 최소 {lo}ms")]
    if hi is not None and ev.duration_ms > hi:
        return [(None, f"{ev.duration_ms}ms — 최대 {hi}ms")]
    return []


@check("too_many_lines")
def _lines(ev: Event, ctx: dict):
    limit = ctx["limits"].get("max_lines")
    if limit and len(ev.lines) > limit:
        return [(None, f"{len(ev.lines)}줄 — 최대 {limit}줄")]
    return []


@check("line_length_exceeded")
def _line_len(ev: Event, ctx: dict):
    limit = ctx["limits"].get("chars_per_line")
    if not limit:
        return []
    weights = ctx["limits"].get("char_weights")
    out = []
    for i, line in enumerate(ev.lines, 1):
        n = count_chars(line, weights)
        if n > limit:
            out.append((i, f"{n:g}자 — 최대 {limit}자"))
    return out


@check("reading_speed_exceeded")
def _cps(ev: Event, ctx: dict):
    speeds = ctx["limits"].get("reading_speed_cps") or {}
    limit = speeds.get("children" if ctx.get("children") else "adult")
    if not limit:
        return []
    weights = ctx["limits"].get("char_weights")
    cps = chars_per_second(ev.text, ev.duration_ms, weights)
    if cps > limit:
        return [(None, f"{cps:.1f} CPS — 최대 {limit} CPS")]
    return []


# --- 문장부호·표기 -------------------------------------------------------


@check("line_end_period_or_comma")
def _line_end_punct(ev: Event, ctx: dict):
    out = []
    for i, line in enumerate(ev.lines, 1):
        s = strip_tags(line).rstrip()
        if s.endswith((".", ",")) and not s.endswith("..."):
            out.append((i, f"…{s[-12:]!r}"))
    return out


@check("three_dot_ellipsis")
def _three_dots(ev: Event, ctx: dict):
    return [(None, "'...' 발견")] if "..." in ev.text else []


@check("em_or_en_dash")
def _dashes(ev: Event, ctx: dict):
    found = [d for d in ("–", "—") if d in ev.text]
    return [(None, f"{' '.join(found)} 발견")] if found else []


@check("double_space")
def _double_space(ev: Event, ctx: dict):
    out = []
    for i, line in enumerate(ev.lines, 1):
        if "  " in strip_tags(line):
            out.append((i, "이중 공백"))
    return out


@check("italics_present")
def _italics(ev: Event, ctx: dict):
    if re.search(r"<i>|</i>|\{\\i1\}", ev.text, re.IGNORECASE):
        return [(None, "이탤릭 태그")]
    return []


@check("acronym_with_periods")
def _acronym(ev: Event, ctx: dict):
    m = re.search(r"\b(?:[A-Za-z]\.){2,}", ev.text)
    return [(None, m.group(0))] if m else []


@check("dual_speaker_marker_format")
def _dual_speaker(ev: Event, ctx: dict):
    """한국어는 하이픈+공백, 영어는 공백 없는 하이픈. 정반대라 사람이 자주 틀린다."""
    marker = (ctx["profile"].get("dual_speaker") or {}).get("marker")
    if not marker:
        return []
    wants_space = marker.endswith(" ")
    out = []
    for i, line in enumerate(ev.lines, 1):
        s = strip_tags(line).lstrip()
        if not s.startswith("-") or s.startswith("--"):
            continue
        has_space = s[1:2] == " "
        if wants_space and not has_space:
            out.append((i, "하이픈 뒤 공백이 없습니다"))
        elif not wants_space and has_space:
            out.append((i, "하이픈 뒤 공백이 있습니다"))
    return out


# --- SDH 표기 -----------------------------------------------------------

BRACKET_RE = re.compile(r"\[([^\]]*)\]")


@check("bracket_unclosed")
def _bracket(ev: Event, ctx: dict):
    s = strip_tags(ev.text)
    if s.count("[") != s.count("]"):
        return [(None, f"'[' {s.count('[')}개 / ']' {s.count(']')}개")]
    return []


@check("forbidden_foreign_marker")
def _foreign_marker(ev: Event, ctx: dict):
    banned = (ctx["profile"].get("foreign_dialogue") or {}).get("forbidden_markers") or []
    hits = [b for b in banned if b in ev.text]
    return [(None, ", ".join(hits))] if hits else []


@check("discouraged_sound_ending")
def _sound_ending(ev: Event, ctx: dict):
    endings = (ctx["profile"].get("sound_effect") or {}).get("discouraged_endings") or []
    out = []
    for inner in BRACKET_RE.findall(strip_tags(ev.text)):
        body = inner.strip().rstrip(".")
        for bad in endings:
            if body.endswith(bad):
                out.append((None, f"[{inner}]"))
                break
    return out


@check("stutter_label")
def _stutter(ev: Event, ctx: dict):
    labels = (ctx["profile"].get("sound_effect") or {}).get("discouraged_labels") or []
    hits = [l for l in labels if l in ev.text]
    return [(None, ", ".join(hits))] if hits else []


@check("music_note_spacing")
def _note_spacing(ev: Event, ctx: dict):
    note = (ctx["profile"].get("music") or {}).get("music_note")
    if not note or not (ctx["profile"].get("music") or {}).get("space_between_note_and_text"):
        return []
    out = []
    for i, line in enumerate(ev.lines, 1):
        s = strip_tags(line).strip()
        if note not in s:
            continue
        if s.startswith(note) and len(s) > 1 and s[1] != " ":
            out.append((i, "여는 음표 뒤 공백 없음"))
        if s.endswith(note) and len(s) > 1 and s[-2] != " ":
            out.append((i, "닫는 음표 앞 공백 없음"))
    return out


@check("music_note_unpaired")
def _note_pair(ev: Event, ctx: dict):
    note = (ctx["profile"].get("music") or {}).get("music_note")
    if not note:
        return []
    out = []
    for i, line in enumerate(ev.lines, 1):
        s = strip_tags(line).strip()
        if note in s and s.count(note) % 2 != 0:
            out.append((i, f"음표 {s.count(note)}개 — 줄 앞뒤로 짝을 맞춥니다"))
    return out


@check("lyric_line_not_capitalized")
def _lyric_caps(ev: Event, ctx: dict):
    music = ctx["profile"].get("music") or {}
    if not music.get("capitalize_line_start"):
        return []
    note = music.get("music_note") or "♪"
    out = []
    for i, line in enumerate(ev.lines, 1):
        s = strip_tags(line).strip()
        if not s.startswith(note):
            continue
        body = s.lstrip(note).strip()
        if body[:1].isalpha() and body[:1].islower():
            out.append((i, f"{body[:20]!r}"))
    return out


def run_checks(events: list[Event], profile: dict, children: bool = False):
    """프로파일이 지정한 검사를 이벤트마다 돌린다.

    반환: (violations, unimplemented_check_names)
    """
    from .model import Violation

    ctx = {"profile": profile, "limits": profile.get("limits") or {}, "children": children}
    violations: list[Violation] = []
    unimplemented: list[str] = []

    for rule in profile.get("rules", []):
        names = rule["check"]
        names = names if isinstance(names, list) else [names]
        for name in names:
            fn = REGISTRY.get(name)
            if fn is None:
                label = f"{rule['id']} ({name})"
                if label not in unimplemented:
                    unimplemented.append(label)
                continue
            for ev in events:
                for line_no, detail in fn(ev, ctx):
                    violations.append(
                        Violation(
                            rule_id=rule["id"],
                            clause=rule["clause"],
                            event_index=ev.index,
                            message=rule["message"],
                            detail=detail,
                            auto_fixable=bool(rule.get("auto")),
                            line_no=line_no,
                        )
                    )

    violations.sort(key=lambda v: (v.event_index, v.rule_id))
    return violations, unimplemented
