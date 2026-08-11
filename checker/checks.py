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


@check("line_break_position")
def _line_break(ev: Event, ctx: dict):
    """한국어 줄바꿈 자리. 언어가 한국어일 때만 본다 — 판정 근거가 한국어 문법이다."""
    from .korean_break import check_line_break

    if (ctx["profile"].get("language") or "") != "ko":
        return []
    weights = (ctx["limits"] or {}).get("char_weights")
    return [(2, problem) for problem in check_line_break(ev.lines, weights)]


@check("line_break_top_heavy")
def _top_heavy(ev: Event, ctx: dict):
    from .korean_break import check_top_heavy

    if (ctx["profile"].get("language") or "") != "ko":
        return []
    weights = (ctx["limits"] or {}).get("char_weights")
    return [(2, problem) for problem in check_top_heavy(ev.lines, weights)]


@check("optimal_cps_exceeded")
def _optimal_cps(ev: Event, ctx: dict):
    """권장 읽기 속도. 상한(`reading_speed_cps`)과 달리 넘어도 규정 위반은 아니다.

    발주처가 "가능하면 이 속도 이하"를 요구할 때 쓴다. 상한을 이미 넘긴 자막은
    그쪽에서 잡히므로 여기서 두 번 말하지 않는다.
    """
    optimal = (ctx["limits"] or {}).get("optimal_cps")
    if not optimal:
        return []
    weights = ctx["limits"].get("char_weights")
    speeds = ctx["limits"].get("reading_speed_cps") or {}
    hard = speeds.get("children" if ctx.get("children") else "adult")
    cps = chars_per_second(ev.text, ev.duration_ms, weights)
    if cps > optimal and not (hard and cps > hard):
        return [(None, f"{cps:.1f} CPS — 권장 {optimal} CPS")]
    return []


@check("words_per_minute_exceeded")
def _wpm(ev: Event, ctx: dict):
    """분당 어절 수. 한국어는 공백으로 어절이 갈리므로 공백 기준으로 센다."""
    limit = (ctx["limits"] or {}).get("words_per_minute")
    if not limit or ev.duration_ms <= 0:
        return []
    words = len([w for w in strip_tags(ev.text).split() if w])
    wpm = words / (ev.duration_ms / 60000.0)
    if wpm > limit:
        return [(None, f"{wpm:.0f} 어절/분 — 최대 {limit}")]
    return []


@check("too_short_to_stand_alone")
def _too_short(ev: Event, ctx: dict):
    """이 길이보다 짧은 자막은 앞뒤와 붙이는 것을 검토하라는 뜻이다.

    최소 표시 시간(`duration_ms.min`)과 다르다. 그쪽은 위반이고 이쪽은 병합 후보다.
    """
    threshold = (ctx["limits"] or {}).get("merge_shorter_than_ms")
    if not threshold:
        return []
    if ev.duration_ms < threshold:
        return [(None, f"{ev.duration_ms}ms — {threshold}ms 미만은 병합을 검토합니다")]
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
    """지양하는 효과음 어미. **대안을 함께 낸다** — 지적만 하면 "그럼 뭐라고 쓰죠"가 남는다."""
    from .lexicon import suggest_text

    endings = (ctx["profile"].get("sound_effect") or {}).get("discouraged_endings") or []
    out = []
    for inner in BRACKET_RE.findall(strip_tags(ev.text)):
        body = inner.strip().rstrip(".")
        for bad in endings:
            if body.endswith(bad):
                marker = f"[{inner}]"
                hint = suggest_text(marker)
                out.append((None, f"{marker} — {hint}" if hint else marker))
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


def run_checks(events: list[Event], profile: dict, children: bool = False,
               fps: float | None = None,
               busy_spans: list[tuple[int, int]] | None = None,
               job_rules=None):
    """프로파일이 지정한 검사를 이벤트마다 돌린다.

    반환: (violations, unimplemented_check_names)
    """
    from .model import Violation

    ctx = {"profile": profile, "limits": profile.get("limits") or {},
           "children": children, "fps": fps, "busy_spans": busy_spans,
           "job_rules": job_rules}

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


# 강사 첨삭 150건에서 되풀이된 지적을 규칙으로 옮긴 것들이다(2026-08-11).
# 규정 문서가 "무엇이 맞는지"를 말한다면 첨삭은 "무엇이 **실제로** 틀리는지"를
# 말한다. 아래 넷은 사람이 매번 눈으로 잡던 것이고, 전부 기계가 볼 수 있다.

# 숫자·단위 뒤에 붙은 '불'만 화폐로 본다. 뒤에 조사나 '짜리'가 붙어도 화폐다.
# `불이 났다`는 앞에 숫자가 없어 걸리지 않는다.
CURRENCY_BUL = re.compile(r"(?<=[\d만천억조])\s*불(?=짜리|[을를은는이가에의와과도만]?(?:\s|$|[,.!?…]))")
# 자막에 쓰지 않는 특수기호. 강사: "자막에는 특수기호를 쓸 수 없습니다.
# 제곱미터라고 표기해 주세요."
SPECIAL_SYMBOLS = {
    "㎡": "제곱미터", "㎢": "제곱킬로미터", "㎝": "센티미터", "㎞": "킬로미터",
    "㎏": "킬로그램", "℃": "도", "℉": "화씨", "㎖": "밀리리터", "ℓ": "리터",
    "²": "제곱", "³": "세제곱", "±": "플러스마이너스", "×": "곱하기", "÷": "나누기",
    "&": "그리고", "＃": "샵",
}
# 시각을 한글로 적은 것. 자료 140행: "시간, 시각: 무조건 아라비아 숫자".
# '세 시에'처럼 조사가 붙어도 시각이다. '시간'·'시계'는 아니다.
HANGUL_CLOCK = re.compile(
    r"(?<![가-힣])(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열한|열두|열)\s*시"
    r"(?=[에는을를쯤경까부터'\s,.!?…]|$)")
# 10 이상을 한글로 적은 것. 자료 138행: "10 이상은 아라비아 숫자".
# 한 글자씩 묶으면 '열다섯'이 '열'+'다'로 잘린다. 낱말 단위로 이어 붙인다.
_TENS = "열|스물|서른|마흔|쉰|예순|일흔|여든|아흔"
_ONES = "하나|한|둘|두|셋|세|넷|네|다섯|여섯|일곱|여덟|아홉"
HANGUL_TEN_PLUS = re.compile(
    rf"(?<![가-힣])(?:{_TENS})(?:{_ONES})?\s*"
    r"(개|명|번|살|가지|마리|대|권|장|병|잔|켤레|자루|시간|분|초|년|달|주)")


@check("currency_bul")
def _currency_bul(ev: Event, ctx: dict):
    """`20만 불` — 화폐 단위 '불'은 쓰지 않는다. 강사 첨삭에서 나온 지적이다.

    숫자나 단위 뒤에 붙은 '불'만 본다. `불이 났다`의 '불'을 고치면 큰일이다.
    """
    for line_no, line in enumerate(ev.lines, 1):
        if CURRENCY_BUL.search(strip_tags(line)):
            yield line_no, "'불' -> '달러'"


@check("special_symbol")
def _special_symbol(ev: Event, ctx: dict):
    """`㎡`, `℃` 같은 조합 문자·기호. 말로 풀어 쓴다."""
    for line_no, line in enumerate(ev.lines, 1):
        found = [f"{s} -> {word}" for s, word in SPECIAL_SYMBOLS.items()
                 if s in strip_tags(line)]
        if found:
            yield line_no, ", ".join(found[:3])


@check("hangul_clock")
def _hangul_clock(ev: Event, ctx: dict):
    """`아홉 시` — 시각은 아라비아 숫자로 적는다."""
    for line_no, line in enumerate(ev.lines, 1):
        found = HANGUL_CLOCK.search(strip_tags(line))
        if found:
            yield line_no, f"'{found.group(0)}' — 시각은 아라비아 숫자로"


@check("hangul_number_ten_plus")
def _hangul_ten_plus(ev: Event, ctx: dict):
    """`열다섯 명` — 10 이상은 아라비아 숫자로 적는다.

    10 미만은 소리 나는 대로 적는 것이 원칙이라 건드리지 않는다(자료 139행).
    """
    for line_no, line in enumerate(ev.lines, 1):
        found = HANGUL_TEN_PLUS.search(strip_tags(line))
        if found:
            yield line_no, f"'{found.group(0)}' — 10 이상은 아라비아 숫자로"


@check("colon_speaker_prefix")
def _colon_speaker(ev: Event, ctx: dict):
    """`이름: 대사` — 대본의 화자 표기가 그대로 실려 나온 자리.

    **어느 플랫폼도, SDH도 번역도 이 표기를 쓰지 않는다.** 원문이 무엇으로 적었든
    자막은 `[이름]`(쿠팡은 `(이름)`)이다. 원문은 번역 과정에서만 의미가 있고
    납품물에 남지 않는다(사용자 지적 2026-08-11).

    시각(`9:30`)은 값이라 건드리지 않는다.
    """
    from .fixes import COLON_SPEAKER

    for line_no, line in enumerate(ev.lines, 1):
        found = COLON_SPEAKER.match(strip_tags(line))
        if found:
            yield line_no, f"'{found.group(3)}:' — 대본 표기가 그대로 남았습니다"


@check("forbidden_punctuation")
def _forbidden_punctuation(ev: Event, ctx: dict):
    """프로파일이 금지한 문장부호가 대사에 들어갔는지.

    **왜 따로 두는가**: 자막을 기계가 만들면 원문의 부호가 그대로 실려 나간다.
    실제로 대본의 화자 표시(`SARAH:`)가 콜론째 자막에 나갔다(2026-08-11). 부호는
    작업자가 가장 민감하게 보는 자리라, 한 글자라도 새면 납품물이 반려된다.

    화자 표시·효과음 안(대괄호·소괄호)은 보지 않는다 — 거기 규칙은 따로 있다.
    """
    policy = (ctx.get("profile") or {}).get("text") or {}
    forbidden = policy.get("forbidden_punctuation") or []
    if not forbidden:
        return

    for line_no, line in enumerate(ev.lines, 1):
        body = re.sub(r"[\[(][^)\]]*[\])]", " ", strip_tags(line))
        # 숫자 사이의 콜론은 부호가 아니라 값이다(9:30, 2:1). 건드리지 않는다.
        body = re.sub(r"(?<=\d)[:](?=\d)", " ", body)
        for mark in forbidden:
            if mark in body:
                yield line_no, f"'{mark}' 발견"


@doc_check("position_collides_with_forced_narrative")
def _position(events: list[Event], ctx: dict):
    """화면자막과 겹치는데 말자막을 옮기지 않았다.

    **SDH·번역 가리지 않는 규칙이다.** 화면에 이미 글자가 있는 자리에 자막을
    얹으면 둘 다 못 읽는다. 겹치는 구간의 말자막은 상단 중앙으로 올린다.

    반대도 잡는다 — 올려 둔 자막을 되돌리지 않은 자국. 앞 장면에서 올린 채로
    두면 그다음부터 자막이 계속 화면 위에 뜬다.
    """
    from .position import suggest_positions

    found = []
    for s in suggest_positions(events, ctx.get("profile"), ctx.get("busy_spans"),
                               ctx.get("job_rules")):
        if s.certain:
            found.append((s.event_index, None, s.reason))
    return found


@doc_check("gap_too_short")
def _gap(events: list[Event], ctx: dict):
    """앞 자막이 끝나고 다음이 시작하기까지의 간격.

    넷플릭스는 이 규정을 **삭제했다**(General Requirements change log 2020-07-24
    "Timing and frame gap sections removed"). 그래서 넷플릭스 프로파일에는 값이
    없고, 발주처가 요구할 때만 `limits.min_gap_ms`로 켠다. SubtitleEdit의 2프레임
    갭 검사는 옛 판본 기준이라 지금 넷플릭스에는 근거가 없다.
    """
    limits = ctx["limits"] or {}
    min_gap = limits.get("min_gap_ms") or 0
    # 프레임 단위 규정은 프레임레이트가 있어야 시간이 된다. 2프레임은 23.976fps에서
    # 83ms, 29.97fps에서 67ms다 — 프레임 수를 밀리초로 굳혀 두면 다른 영상에서 틀린다.
    frames = limits.get("min_gap_frames")
    if frames:
        fps = ctx.get("fps") or 23.976
        min_gap = max(min_gap, frames * 1000.0 / fps)
    if not min_gap:
        return []
    out = []
    ordered = sorted(events, key=lambda e: e.start_ms)
    for prev, cur in zip(ordered, ordered[1:]):
        gap = cur.start_ms - prev.end_ms
        if gap < 0:
            out.append((cur.index, None, f"앞 자막과 {-gap}ms 겹칩니다"))
        elif gap < min_gap:
            out.append((cur.index, None, f"간격 {gap}ms — 최소 {min_gap:.0f}ms"))
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


# --- 실무 자료에서 나온 검사 ---------------------------------------------
#
# 작업자가 실제 작업하며 정리한 자료(rules/sources/작업자-자료)에서 왔다.
# 공식 가이드에 없거나 명시되지 않은 것이 있어 프로파일이 켜야 적용된다.

UNIT_COMPOSED = "㎡㎥㎢㎠㎣㎝㎜㎞㎏㎎㎖㎗㎘℃℉㎈㎉㎐㎑㎒㎓㎧㎨㏄㏊㎀㎁㎂㎃㎄"


@check("space_between_markers")
def _space_between_markers(ev: Event, ctx: dict):
    """`(철수) [작게]` — 표시와 표시 사이에 공백이 있다.

    **표시끼리는 붙여 쓴다.** 자막 위치·화자명·어조·효과음 표기가 연달아 오면 사이를
    띄우지 않고, 마지막 표시와 **대사** 사이에만 한 칸을 둔다(사용자 지정
    2026-08-02 교정기, 2026-08-11 재확인).

        (철수)[작게] 왜 이래        (o)
        (철수) [작게] 왜 이래       (x)

    **처음에는 정반대로 검사하고 있었다.** 작업자 자료 206행에 "(화자명)과
    [외국어/효과음]을 나란히 쓰는 경우에는 둘 사이 띄어쓰기"라고 적혀 있어 그대로
    옮겼는데, 사용자가 바로잡았다. 한국어 교정기는 처음부터 붙여 쓰고 있었으므로
    두 도구가 서로 반대로 고치고 있었던 셈이다 — 같은 규칙을 두 벌로 적으면
    반드시 이렇게 어긋난다.

    표시만 있고 대사가 없는 줄(효과음만 있는 줄)은 보지 않는다.
    """
    from .position import POSITION_TAG

    profile = ctx.get("profile") or {}
    speaker = ((profile.get("speaker_id") or {}).get("enclosure") or "[]")
    tone = ((profile.get("tone") or {}).get("enclosure")
            or (profile.get("sound_effect") or {}).get("enclosure") or "[]")
    pairs = {speaker, tone, "[]", "()"}
    openers = "".join(re.escape(p[0]) for p in pairs if p)
    closers = "".join(re.escape(p[-1]) for p in pairs if p)
    gap = re.compile(rf"(?:[{closers}]|\}})[ \t]+[{openers}]")

    out = []
    for i, line in enumerate(ev.lines, 1):
        body = strip_tags(line)
        if gap.search(POSITION_TAG.sub(lambda m: m.group(0), body)) and _has_dialogue(body):
            out.append((i, "표시끼리는 붙여 씁니다"))
    return out


def _has_dialogue(line: str) -> bool:
    """표시를 걷어내고도 글자가 남는지. 남지 않으면 효과음만 있는 줄이다."""
    return bool(re.sub(r"[\[(][^)\]]*[\])]|\{[^}]*\}", "", line).strip())


@check("discouraged_silence_expression")
def _silence_expr(ev: Event, ctx: dict):
    """`[정적]`·`[조용해진다]` — 어느 OTT를 막론하고 지양한다."""
    banned = (ctx["profile"].get("sound_effect") or {}).get("discouraged_expressions") or []
    hits = [b for b in banned if b in ev.text]
    return [(None, ", ".join(hits))] if hits else []


@check("dialogue_double_quote")
def _dialogue_double_quote(ev: Event, ctx: dict):
    """말자막의 큰따옴표. 화면 자막에는 규칙에 따라 쓰이므로 확인만 구한다."""
    out = []
    for i, line in enumerate(ev.lines, 1):
        s = strip_tags(line)
        if '"' in s or "“" in s or "”" in s:
            out.append((i, "말자막이면 큰따옴표를 쓰지 않습니다"))
    return out


@check("unit_composed_character")
def _unit_composed(ev: Event, ctx: dict):
    hits = sorted({c for c in ev.text if c in UNIT_COMPOSED})
    return [(None, f"{' '.join(hits)} — 조합 문자 대신 풀어 씁니다")] if hits else []


@check("ampersand_outside_initialism")
def _ampersand(ev: Event, ctx: dict):
    """`&`는 및·겸·쉼표로 바꾼다. 약어 안의 `&`(R&B, B&B)는 규정이 허용한다."""
    s = strip_tags(ev.text)
    for m in re.finditer(r"&", s):
        left, right = s[max(0, m.start() - 1): m.start()], s[m.end(): m.end() + 1]
        if left.isupper() and right.isupper():
            continue  # R&B 같은 약어
        return [(None, "'&'는 및·겸·쉼표로 바꿉니다")]
    return []


@check("middle_initial_period")
def _middle_initial(ev: Event, ctx: dict):
    """`John F. Kennedy`의 `F.` — 가운데 이름 뒤 온점은 떼고 쓴다."""
    m = re.search(r"(?<![A-Za-z])[A-Z]\.(?=\s)", strip_tags(ev.text))
    return [(None, f"{m.group(0)} — 가운데 이름 뒤 온점을 뗍니다")] if m else []


@check("effect_after_dialogue")
def _effect_after_dialogue(ev: Event, ctx: dict):
    """대사 뒤에 붙은 효과음. 쿠팡은 이것을 허용하지 않는다."""
    out = []
    for i, line in enumerate(ev.lines, 1):
        s = strip_tags(line).strip()
        m = re.search(r"\[[^\]]+\]\s*$", s)
        if not m:
            continue
        before = s[: m.start()].strip()
        # 앞이 화자명뿐이면 대사가 아니다
        if before and not re.fullmatch(r"[-\s]*[\[(][^\])]*[\])]", before):
            out.append((i, f"대사 뒤 효과음 {m.group(0)}"))
    return out


@check("ellipsis_style_mismatch")
def _ellipsis_style(ev: Event, ctx: dict):
    """말줄임표 표기가 플랫폼마다 **정반대**다.

    넷플릭스는 전각(`…`), 쿠팡은 점 셋(`...`), 디즈니는 둘 다 되지만 작업물 안에서
    통일해야 한다. 한쪽 기준으로 고쳐 주면 다른 쪽에서는 그것이 위반이 된다.
    """
    want = (ctx["profile"].get("text") or {}).get("ellipsis_char")
    if not want:
        return []
    s = strip_tags(ev.text)
    if want == "…" and "..." in s:
        return [(None, "'...' -> '…'")]
    if want == "..." and "…" in s:
        return [(None, "'…' -> '...'")]
    return []


@doc_check("ellipsis_style_inconsistent")
def _ellipsis_mixed(events: list[Event], ctx: dict):
    """표기를 고르는 것은 발주처지만, **섞어 쓰는 것은 어느 쪽에서도 틀렸다.**"""
    if not (ctx["profile"].get("text") or {}).get("ellipsis_consistency_required"):
        return []
    full = [e for e in events if "…" in strip_tags(e.text)]
    dots = [e for e in events if "..." in strip_tags(e.text)]
    if full and dots:
        first = min(full[0].index, dots[0].index)
        return [(first, None,
                 f"전각 {len(full)}건, 점 셋 {len(dots)}건이 섞였습니다 — 한쪽으로 통일합니다")]
    return []


@check("double_punctuation")
def _double_punct(ev: Event, ctx: dict):
    """`?!`·`!?`·`!!` 같은 이중 부호. 디즈니·쿠팡은 금지, 넷플릭스는 남용 금지다."""
    policy = (ctx["profile"].get("text") or {}).get("double_punctuation")
    if policy not in ("forbidden", "limited"):
        return []
    m = re.search(r"[?!]{2,}", strip_tags(ev.text))
    return [(None, m.group(0))] if m else []


@check("tilde_used")
def _tilde(ev: Event, ctx: dict):
    """물결표. 디즈니·쿠팡은 금지, 넷플릭스는 `오~` 정도만 허용하고 남용 금지."""
    policy = (ctx["profile"].get("text") or {}).get("tilde")
    if policy != "forbidden":
        return []
    return [(None, "'~'")] if "~" in strip_tags(ev.text) else []


@check("sound_effect_multiline")
def _effect_multiline(ev: Event, ctx: dict):
    """효과음은 반드시 한 줄로 쓴다. 대괄호가 줄을 넘으면 쪼개진 것이다."""
    for i, line in enumerate(ev.lines, 1):
        s = strip_tags(line)
        if s.count("[") != s.count("]"):
            return [(i, "효과음 표기가 줄을 넘어갑니다 — 한 줄로 씁니다")]
    return []


@check("music_marker_style")
def _music_marker(ev: Event, ctx: dict):
    """음악 효과음의 음표 표기. **디즈니는 대괄호 안에 ♪를 넣고 나머지는 넣지 않는다.**

    `[♪ 잔잔한 음악]`(디즈니) vs `[잔잔한 음악]`(넷플릭스·쿠팡).
    가사 자막의 음표(`♪ 가사 ♪`)와는 다른 자리다 — 여기는 대괄호 **안**이다.
    """
    music = ctx["profile"].get("music") or {}
    want = music.get("note_inside_bracket")
    if want is None:
        return []
    keywords = ("음악", "곡", "연주", "노래")
    out = []
    for inner in BRACKET_RE.findall(strip_tags(ev.text)):
        if not any(k in inner for k in keywords):
            continue
        has_note = "♪" in inner
        if want and not has_note:
            out.append((None, f"[{inner}] — 음악 효과음에는 ♪를 넣습니다"))
        elif not want and has_note:
            out.append((None, f"[{inner}] — 음악 효과음에 ♪를 넣지 않습니다"))
    return out


@check("bleep_mask_character")
def _bleep_mask(ev: Event, ctx: dict):
    """삐 처리 문자. 넷플릭스·쿠팡은 별표, **디즈니는 대문자 O**를 쓴다."""
    censorship = ctx["profile"].get("censorship") or {}
    mask = censorship.get("bleeped_word")
    if not mask:
        return []
    s = strip_tags(ev.text)
    if mask == "*" and re.search(r"O{1,}(?=[가-힣])|(?<=[가-힣])O{1,}", s):
        return [(None, "삐 처리는 별표(*)로 합니다")]
    if mask == "O" and re.search(r"\*+(?=[가-힣])|(?<=[가-힣])\*+", s):
        return [(None, "삐 처리는 대문자 O로 합니다")]
    return []


@check("full_bleep_style")
def _full_bleep(ev: Event, ctx: dict):
    """문장 전체가 삐 처리됐을 때. 넷플릭스는 별표를 늘어놓고, 디즈니·쿠팡은 효과음으로 쓴다."""
    censorship = ctx["profile"].get("censorship") or {}
    style = censorship.get("full_sentence_bleep")
    if not style:
        return []
    s = strip_tags(ev.text)
    has_run = bool(re.search(r"[*O]{2,}(\s+[*O]{2,})+", s))
    has_marker = "음 소거" in s
    if style == "[음 소거 효과음]" and has_run:
        return [(None, "여러 단어가 삐 처리되면 [음 소거 효과음]으로 씁니다")]
    if style != "[음 소거 효과음]" and has_marker:
        return [(None, "여러 단어가 삐 처리되면 부호를 늘어놓습니다([음 소거 효과음] 아님)")]
    return []


SPEAKER_AT_HEAD = re.compile(r"^\s*-?\s*([\[(])([^\])]+)([\])])\s*(.*)$")


@check("speaker_id_enclosure")
def _speaker_enclosure(ev: Event, ctx: dict):
    """화자명 괄호. **쿠팡은 소괄호, 넷플릭스·디즈니는 대괄호**를 쓴다.

    효과음은 셋 다 대괄호이므로, 줄 맨 앞에서 뒤에 대사가 이어지는 자리만 본다.
    """
    want = (ctx["profile"].get("speaker_id") or {}).get("enclosure")
    if want not in ("[]", "()"):
        return []
    out = []
    for i, line in enumerate(ev.lines, 1):
        m = SPEAKER_AT_HEAD.match(strip_tags(line))
        if not m or not m.group(4).strip():
            continue
        used = m.group(1) + m.group(3)
        if used != want:
            out.append((i, f"{used} -> {want} 로 씁니다"))
    return out


@check("speaker_id_conjunction")
def _speaker_conjunction(ev: Event, ctx: dict):
    """여럿이 동시에 말할 때. `[철수와 영희]`(x) -> `[철수, 영희]`·`[함께]`(o)."""
    out = []
    for i, line in enumerate(ev.lines, 1):
        m = SPEAKER_AT_HEAD.match(strip_tags(line))
        if not m or not m.group(4).strip():
            continue
        inner = m.group(2)
        if re.search(r"[가-힣]{1,6}(와|과)\s+[가-힣]", inner):
            out.append((i, f"[{inner}] — 쉼표로 나열하거나 [함께]로 씁니다"))
    return out


@check("speaker_id_alone_on_line")
def _speaker_alone(ev: Event, ctx: dict):
    """화자명과 대사 첫마디는 반드시 같은 줄에 둔다."""
    lines = [strip_tags(l).strip() for l in ev.lines]
    out = []
    for i, line in enumerate(lines):
        if i + 1 >= len(lines) or not lines[i + 1]:
            continue
        if re.fullmatch(r"-?\s*[\[(][^\])]+[\])]", line) and not lines[i + 1].startswith(("[", "(", "-", "♪")):
            out.append((i + 1, f"{line} — 대사 첫마디와 같은 줄에 둡니다"))
    return out


@check("lyrics_punctuation")
def _lyrics_punct(ev: Event, ctx: dict):
    """가사의 문장부호. 넷플릭스·디즈니는 쉼표를 허용하고 **쿠팡은 쉼표·따옴표를 금지**한다."""
    songs = ctx["profile"].get("songs") or {}
    banned = songs.get("forbidden_punctuation")
    if not banned:
        return []
    note = (ctx["profile"].get("music") or {}).get("music_note") or "♪"
    out = []
    for i, line in enumerate(ev.lines, 1):
        s = strip_tags(line).strip()
        if note not in s:
            continue
        hits = [c for c in banned if c in s]
        if hits:
            out.append((i, f"가사에 {' '.join(hits)} — 쓰지 않습니다"))
    return out


@check("lyrics_with_dialogue")
def _lyrics_with_dialogue(ev: Event, ctx: dict):
    """가사와 대사를 한 자막에 넣은 것. 디즈니는 이것을 지양한다."""
    songs = ctx["profile"].get("songs") or {}
    if songs.get("lyrics_with_dialogue_in_one_event") != "forbidden":
        return []
    note = (ctx["profile"].get("music") or {}).get("music_note") or "♪"
    lines = [strip_tags(l).strip() for l in ev.lines if strip_tags(l).strip()]
    has_lyric = any(note in l for l in lines)
    has_dialogue = any(note not in l and not re.fullmatch(r"-?\s*[\[(][^\])]*[\])]", l) for l in lines)
    if has_lyric and has_dialogue:
        return [(None, "가사와 대사를 한 자막에 넣지 않습니다 — 자막을 나눕니다")]
    return []


@check("translator_credit_present")
def _translator_credit(ev: Event, ctx: dict):
    """자막 제작자 크레딧. 쿠팡만 넣고 넷플릭스·디즈니는 넣지 않는다."""
    if (ctx["profile"].get("credit") or {}).get("translator_credit") != "forbidden":
        return []
    if re.search(r"자막\s*[:：]", strip_tags(ev.text)):
        return [(None, "이 플랫폼은 자막 제작자 크레딧을 넣지 않습니다")]
    return []


@doc_check("first_event_at_zero")
def _first_at_zero(events: list[Event], ctx: dict):
    """첫 자막 인점이 00:00:00:00이면 안 된다(쿠팡). 몇 프레임이라도 띄운다."""
    if not (ctx["profile"].get("delivery") or {}).get("first_cue_not_at_zero"):
        return []
    if not events:
        return []
    first = min(events, key=lambda e: e.start_ms)
    if first.start_ms <= 0:
        return [(first.index, None, "첫 자막 인점을 00:00:00:00으로 두지 않습니다")]
    return []


# `6만 ~ 8만`처럼 단위가 사이에 끼면 숫자만 보는 패턴으로는 안 잡힌다
# (`만` 때문에 앞쪽이 \d가 아니다). 단위 글자까지 포함해서 본다.
RANGE_BAD_SPACE = re.compile(r"(?:\d|[만천억백])\s+[~\-–—]\s*\d|\d\s*[~\-–—]\s+\d")
RANGE_UNIT_DROPPED = re.compile(r"(?<![\d,])(\d+)\s*[~\-–—]\s*(\d+)\s*(만|천|억|백)")
CONJUNCTIVE_ADVERB = re.compile(r"^(그러나|또한|사실|하지만|그런데|그리고|따라서|그래서|즉|물론),")


@check("range_notation")
def _range_notation(ev: Event, ctx: dict):
    """범위 표기. `6만~8만 명`(o) / `6~8만 명`·`6만 ~ 8만 명`(x).

    물결표·붙임표 앞뒤를 띄우지 않고, 앞쪽 수에도 단위를 붙인다.
    """
    if not (ctx["profile"].get("numbers") or {}).get("range_notation_strict"):
        return []
    s = strip_tags(ev.text)
    out = []
    m = RANGE_BAD_SPACE.search(s)
    if m:
        out.append((None, f"{m.group(0).strip()} — 범위 부호 앞뒤를 띄우지 않습니다"))
    m = RANGE_UNIT_DROPPED.search(s)
    if m:
        out.append((None, f"{m.group(0)} — 앞쪽 수에도 단위를 붙입니다"
                          f"({m.group(1)}{m.group(3)}~{m.group(2)}{m.group(3)})"))
    return out


@check("conjunctive_adverb_comma")
def _conjunctive_comma(ev: Event, ctx: dict):
    """접속부사 뒤 쉼표. `그러나,`·`또한,`·`사실,`은 쓰지 않는다."""
    if not (ctx["profile"].get("text") or {}).get("no_comma_after_conjunctive_adverb"):
        return []
    out = []
    for i, line in enumerate(ev.lines, 1):
        m = CONJUNCTIVE_ADVERB.match(strip_tags(line).strip())
        if m:
            out.append((i, f"{m.group(1)}, — 접속부사 뒤에는 쉼표를 쓰지 않습니다"))
    return out
