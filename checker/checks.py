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


def excerpt(event: Event, line_no: int | None, limit: int = 60) -> str:
    """문제가 난 줄(줄 번호가 없으면 자막 전체)을 리포트에 실을 만큼만 자른다."""
    if line_no and 1 <= line_no <= len(event.lines):
        text = event.lines[line_no - 1]
    else:
        text = event.text.replace("\n", " / ")
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def run_checks(events: list[Event], profile: dict, children: bool = False):
    """프로파일이 지정한 검사를 이벤트마다 돌린다.

    반환: (violations, unimplemented_check_names)
    """
    from .model import Violation

    ctx = {"profile": profile, "limits": profile.get("limits") or {}, "children": children}

    limits = ctx["limits"]
    speeds = limits.get("reading_speed_cps") or {}
    duration = limits.get("duration_ms") or {}
    # 문구에 숫자를 박아 두면 발주처가 값을 조였을 때 리포트가 거짓말을 한다.
    # 프로파일 값으로 채우게 하고, 자리표시자가 없는 문구는 그대로 둔다.
    fields = {
        "chars_per_line": limits.get("chars_per_line"),
        "max_lines": limits.get("max_lines"),
        "cps_adult": speeds.get("adult"),
        "cps_children": speeds.get("children"),
        "cps": speeds.get("children" if children else "adult"),
        "duration_min_ms": duration.get("min"),
        "duration_max_ms": duration.get("max"),
    }

    def render(message: str) -> str:
        try:
            return message.format(**fields)
        except (KeyError, IndexError, ValueError):
            return message
    violations: list[Violation] = []
    unimplemented: list[str] = []

    for rule in profile.get("rules", []):
        names = rule["check"]
        names = names if isinstance(names, list) else [names]
        for name in names:
            doc_fn = DOC_REGISTRY.get(name)
            if doc_fn is not None:
                by_index = {e.index: e for e in events}
                for event_index, line_no, detail in doc_fn(events, ctx):
                    ev = by_index.get(event_index)
                    violations.append(
                        Violation(
                            rule_id=rule["id"],
                            clause=rule["clause"],
                            event_index=event_index,
                            message=render(rule["message"]),
                            detail=detail,
                            auto_fixable=bool(rule.get("auto")),
                            line_no=line_no,
                            text=excerpt(ev, line_no) if ev else "",
                        )
                    )
                continue
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
                            message=render(rule["message"]),
                            detail=detail,
                            auto_fixable=bool(rule.get("auto")),
                            line_no=line_no,
                            text=excerpt(ev, line_no),
                        )
                    )

    violations.sort(key=lambda v: (v.event_index, v.rule_id))
    return violations, unimplemented


# --- 문서 단위 검사 -------------------------------------------------------
#
# 자막 하나만 봐서는 알 수 없고 파일 전체를 훑어야 하는 검사다. 이벤트 단위
# 검사와 계약이 달라 레지스트리를 나눈다.
#   fn(events, ctx) -> list[tuple[event_index, line_no | None, detail]]

DOC_REGISTRY: dict[str, callable] = {}


def doc_check(name: str):
    def deco(fn):
        DOC_REGISTRY[name] = fn
        return fn

    return deco


SPEAKER_ID_RE = re.compile(r"^\s*-?\s*\[([^\]]+)\]\s*(.*)$")


def speaker_ids(events: list[Event]) -> list[tuple[str, int, int]]:
    """화자 표시만 뽑는다: (라벨, event_index, line_no).

    줄 맨 앞 대괄호 **뒤에 대사가 이어질 때만** 화자 표시로 본다. 대괄호만 있는
    줄은 효과음이다(`[문이 쾅 닫히는 소리]`) — 둘을 섞으면 효과음 문구가 화자
    이름으로 잡혀 일관성 검사가 무의미해진다.
    """
    found = []
    for ev in events:
        for line_no, line in enumerate(ev.lines, 1):
            m = SPEAKER_ID_RE.match(strip_tags(line))
            if m and m.group(2).strip():
                found.append((m.group(1).strip(), ev.index, line_no))
    return found


def _base_label(label: str) -> str:
    """뒤에 붙은 번호를 뗀다. `[남자 1]`·`[남자 2]`는 규정이 허용하는 구분이다."""
    return re.sub(r"\s*\d+$", "", label)


@doc_check("gap_too_short")
def _gap(events: list[Event], ctx: dict):
    """앞 자막이 끝나고 다음이 시작하기까지의 간격.

    넷플릭스는 이 규정을 **삭제했다**(General Requirements change log 2020-07-24
    "Timing and frame gap sections removed"). 그래서 넷플릭스 프로파일에는 값이
    없고, 발주처가 요구할 때만 `limits.min_gap_ms`로 켠다. SubtitleEdit의 2프레임
    갭 검사는 옛 판본 기준이라 지금 넷플릭스에는 근거가 없다.
    """
    min_gap = (ctx["limits"] or {}).get("min_gap_ms")
    if not min_gap:
        return []
    out = []
    ordered = sorted(events, key=lambda e: e.start_ms)
    for prev, cur in zip(ordered, ordered[1:]):
        gap = cur.start_ms - prev.end_ms
        if gap < 0:
            out.append((cur.index, None, f"앞 자막과 {-gap}ms 겹칩니다"))
        elif gap < min_gap:
            out.append((cur.index, None, f"간격 {gap}ms — 최소 {min_gap}ms"))
    return out


@doc_check("speaker_id_inconsistent")
def _speaker_consistency(events: list[Event], ctx: dict):
    labels = speaker_ids(events)
    if not labels:
        return []

    first_seen: dict[str, tuple[int, int]] = {}
    for label, ev_index, line_no in labels:
        first_seen.setdefault(label, (ev_index, line_no))

    out = []
    reported: set[tuple[str, str]] = set()

    # ① 공백만 다른 표기 — 같은 이름을 두 가지로 적은 것이라 확정 위반이다.
    by_normal: dict[str, list[str]] = {}
    for label in first_seen:
        by_normal.setdefault(label.replace(" ", ""), []).append(label)
    for variants in by_normal.values():
        if len(variants) > 1:
            variants = sorted(variants)
            ev_index, line_no = first_seen[variants[-1]]
            out.append((ev_index, line_no,
                        "같은 이름을 다르게 적었습니다: " + " / ".join(f"[{v}]" for v in variants)))
            reported.add((variants[0], variants[-1]))

    # ② 한쪽이 다른 쪽에 포함되는 표기 — `[김 경위]`와 `[경위]`처럼 같은 인물일
    #    가능성이 크다. 다만 규정은 전개에 따른 변경을 허용하므로 확인만 구한다.
    names = sorted(first_seen, key=lambda x: first_seen[x])
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            na, nb = _base_label(a).replace(" ", ""), _base_label(b).replace(" ", "")
            if not na or not nb or na == nb:
                continue
            if (na in nb or nb in na) and (a, b) not in reported and (b, a) not in reported:
                ev_index, line_no = first_seen[b]
                out.append((ev_index, line_no,
                            f"[{a}]와 [{b}]가 같은 인물이면 하나로 통일해야 합니다"
                            " (전개상 의도적 변경이면 그대로 두세요)"))
                reported.add((a, b))

    return out
