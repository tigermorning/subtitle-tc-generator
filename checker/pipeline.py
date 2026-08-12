"""단계 하나짜리 함수들과, 그것을 잇는 유일한 경로.

**왜 있는가.** 오케스트레이션이 세 곳에 흩어져 있었다 — `cli.py`, `app/jobs.py`,
`plugin.py`. 그 결과 **같은 자막에 같은 설정을 줘도 입구마다 다른 리포트가 나왔다.**

    cli.py 검사 명령    검사 -> 한국어 교정 -> 규정 자동교정      리포트 = 교정 **전**
    cli.py 생성 명령    한국어 교정 -> 규정 자동교정 -> 검사      리포트 = 교정 **후**
    app/jobs.py         한국어 교정 -> 규정 자동교정 -> 검사      리포트 = 교정 **후**
    plugin.py           검사 -> 한국어 교정 -> 규정 자동교정      리포트 = 교정 **전**

지워진 `runner.py`가 경고하던 것이 그대로 벌어져 있었다("입구가 둘이라고 로직이
둘이면 언젠가 갈라진다"). 그 파일은 아무도 쓰지 않아 경고 역할을 못 했다.

**이 모듈은 그 경고를 코드로 만든다.** 어댑터(CLI·GUI·플러그인·앞으로의 HTTP)는
여기 있는 함수만 부른다. 코어 모듈을 직접 부르지 않는다.

## 정해진 순서

    한국어 교정  ->  규정 자동교정  ->  규정 검사

**검사가 맨 끝이다.** 근거는 "리포트가 최종 자막을 설명해야 한다"만이 아니다 — 그것만
이면 원본을 검사하는 쪽(옛 `plugin.py`)에도 장점이 있다. 그쪽은 위반마다 `[자동]`/
`[확인]`을 표시하므로 **도구가 무엇을 했는지** 사용자가 본다. 전문가의 신뢰에 직결된다.

결정적인 이유는 다른 데 있다. **교정이 만든 새 위반을 놓치기 때문이다.**

    한국어 교정이 '안되요' -> '안 돼요'로 한 글자 늘린다
      -> 줄 길이·CPS 위반이 새로 생긴다
      -> 원본만 검사했으면 그것을 못 본다

이 프로젝트는 놓치는 쪽보다 알리는 쪽을 택해 왔다. 그래서 최종 검사다.

**대가를 적어 둔다.** "원본에 무엇이 있었는지"가 리포트에서 약해진다. 자동으로 고친
내역은 `extra["applied"]`와 고친 줄 수로 따로 보고하지만, 위반 목록만큼 자세하지 않다.
자막별 diff를 붙여 이 대가를 메우는 것은 나중 일이다.

**한국어 교정이 규정 자동교정보다 먼저다.** 교정이 글자 수를 바꾸고, 규정 검사·자동
교정은 글자 수에 의존한다(CPS·줄 길이). 순서를 뒤집으면 방금 맞춰 놓은 길이가 다시
어긋난다. 같은 이유로 재분할은 번역 뒤에 온다(`resplit.py` 서두).

## 단계는 각자 독립적으로 돌 수 있다

`STAGES`에 선언된 단계는 앞 단계 없이도 부를 수 있다 — 작업자가 이미 자막을 갖고
있으면 생성을 건너뛰고 교정만 돌린다. 앞으로 번역·번역 QA가 붙어도 목록에 한 줄만
더한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import check_events
from .fixes import apply_fixes
from .korean import CorrectorUnavailable, load_backend, run_korean_pass
from .model import Event

Progress = Callable[[str], None]


def _silent(_message: str) -> None:
    """진행 상황을 아무데도 안 보낸다. 어댑터가 콜백을 안 주면 이것을 쓴다."""


def _edits(before: list[Event], after: list[Event]) -> list[dict]:
    """무엇이 어떻게 바뀌었는지 줄 단위로 남긴다.

    **몇 곳 고쳤다는 숫자만으로는 부족하다.** 검사가 맨 끝으로 가면 자동으로 고친
    위반은 리포트에서 사라진다 — 사라진 자리에 이 목록이 들어가야 사용자가 도구가
    한 일을 되짚을 수 있다. 규칙 이름만 남기면 어느 줄이 바뀌었는지 알 수 없다.
    """
    return [{"event_index": a.index, "before": a.text, "after": b.text}
            for a, b in zip(before, after) if a.text != b.text]


# ---------------------------------------------------------------- 단계 결과

@dataclass
class StageResult:
    """단계 하나의 결과. **입력을 바꾸지 않고 새 목록을 돌려준다.**

    `events`가 그 단계가 내놓은 자막이고, `notes`는 사용자에게 알려야 하는 사실이다
    (건너뛴 이유 등). `violations`는 검사 단계만 채운다.

    `notes`가 중요하다 — 한국어 교정기를 못 찾아 건너뛴 경우가 **통과로 보이면 안
    된다**(`plugin.py`가 이미 그렇게 하고 있었고 그 판단을 그대로 옮겼다).
    """

    events: list[Event]
    notes: list[str] = field(default_factory=list)
    violations: list[dict] = field(default_factory=list)
    changed: int = 0
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- 단계 ① 생성

def stage_generate(video: Path, profile: dict, *, script: Path | None = None,
                   language: str = "auto", translator=None, speech_method: str = "auto",
                   progress: Progress | None = None) -> StageResult:
    """영상에서 자막 초안을 만든다. 전사 -> 대조 -> 재분할 -> 스포팅.

    **한국어 교정을 여기서 부르지 않는다.** 초안을 사람이 먼저 보게 하는 것이 이
    도구의 방식이고(`generate.py` 서두), 교정은 그 다음 단계다.
    """
    from .generate import generate

    say = progress or _silent
    draft = generate(video, profile, script=script, language=language,
                     translator=translator, speech_method=speech_method, progress=say)
    # `draft.notes`는 `(자막 번호, 봐야 할 이유)` 튜플 목록이다 — 단계 전체에 대한
    # 안내인 `StageResult.notes`와 성격이 다르므로 섞지 않고 `extra`로 넘긴다.
    return StageResult(events=list(draft.events), extra={"draft": draft})


# ---------------------------------------------------------------- 번역과 감수

def stage_translate(events: list[Event], profile: dict, *, translator,
                    glossary=None, progress: Progress | None = None) -> StageResult:
    """1차 번역. **받은 타임코드를 그대로 물려받고 확인한다.**

    작업자 자료 190행: "TC 작업이 되어 온 파일에 내가 번역만 한 경우는 TC를 절대
    건드리면 안 됨!" 그래서 여기서 잰다 — 전에는 CLI만 확인하고 GUI는 확인하지
    않았다. 어긋나면 `violations`에 넣어 어댑터가 막을 수 있게 한다.
    """
    from .translate import Glossary, to_events, translate_events

    say = progress or _silent
    glossary = glossary if glossary is not None else Glossary.from_profile(profile)
    say(f"한국어로 옮깁니다 — 자막 {len(events)}개")
    cues = translate_events(events, translator, glossary, progress=say)
    translated = to_events(cues, events)

    violations: list[dict] = []
    before = [(e.index, e.start_ms, e.end_ms) for e in events]
    after = [(e.index, e.start_ms, e.end_ms) for e in translated]
    if before != after:
        violations.append({
            "event_index": 0, "rule_id": "TC00", "source": "pipeline",
            "message": "번역이 타임코드를 바꿨습니다. 결과를 쓰지 마세요.",
        })

    return StageResult(
        events=translated,
        changed=len(_edits(events, translated)),
        violations=violations,
        # 확인이 필요한 자리. **번역을 못 한 자막은 빈칸이 아니라 원문이 남는다**
        # (빈칸은 지나치지만 원문은 눈에 띈다) — 그 자리를 여기로 낸다.
        extra={"cues": cues,
               "notes_by_index": [{"event_index": c.index, "note": c.note}
                                  for c in cues if c.note]},
    )


def stage_revise(events: list[Event], profile: dict, *, translator,
                 source: dict[int, str] | None = None, glossary=None,
                 rounds: int = 1, first_round: int = 2,
                 progress: Progress | None = None) -> StageResult:
    """감수를 `rounds`번 돈다. **회차를 하드코딩하지 않는다.**

    전에는 두 어댑터가 각자 `("2차", "3차")[:passes - 1]`을 적어 두어 3차를 넘길 수
    없었다. 이제 회차는 인자다.

    첫 회차는 **감수**(오역·용어·맥락 — 원문을 함께 보여 준다), 그 뒤는 **윤문**
    (말맛만). 사람이 하는 순서를 그대로 따른 것이다(작업자 자료 569~579행).

    **바꾼 내역을 버리지 않는다.** 전에는 GUI가 `events, _ = revise(...)`로 받아
    무엇이 바뀌었는지 사용자가 볼 수 없었다 — 한국어 위반을 버리던 것과 같은 무늬다.
    """
    from .revise import revise

    say = progress or _silent
    current = list(events)
    all_revisions = []
    per_round = []

    for n in range(rounds):
        label = f"{first_round + n}차"
        role = "감수" if n == 0 else "윤문"
        say(f"{label} ({role})")
        current, revisions = revise(current, translator, source=source,
                                    glossary=glossary, stage=label, role=role,
                                    progress=say)
        all_revisions += revisions
        per_round.append({"stage": label, "role": role,
                          "changed": sum(1 for r in revisions if r.changed)})

    return StageResult(
        events=current,
        changed=len(_edits(events, current)),
        extra={"revisions": all_revisions, "rounds": per_round},
    )


def stage_terms(events: list[Event], profile: dict | None = None, *,
                corrector_path: str | None = None, knp: Path | None = None,
                web: bool = False, translator=None,
                progress: Progress | None = None) -> StageResult:
    """용어를 뽑아 조사한다. 자막은 건드리지 않는다 — 표만 낸다.

    두 어댑터가 같은 순서를 각자 적어 두었던 자리다(뽑기 -> 규범 용례 -> KNP ->
    조사 -> 설명). 조회가 막히면 **건너뛴 사실을 `notes`에 남기고** 나머지를 계속
    돈다 — 조용히 빠지면 "조사 다 했다"가 거짓말이 된다.
    """
    from .terms import extract, research, summarize

    say = progress or _silent
    notes: list[str] = []
    terms = extract([e.text for e in events])
    say(f"용어 후보 {len(terms)}개")

    lookup = None
    if corrector_path:
        try:
            from .cli import _loanword_lookup
            lookup = _loanword_lookup(Path(corrector_path))
        except Exception as exc:
            notes.append(f"규범 용례 조회를 건너뜁니다: {exc}")

    glossary: dict = {}
    if knp:
        from .knp import read_terms
        glossary = read_terms(knp)

    research(terms, lookup=lookup, glossary=glossary, web=web, progress=say)

    if translator is not None:
        try:
            from .terms import explain
            explain(terms, translator, progress=say)
        except Exception as exc:
            notes.append(f"용어 설명을 건너뜁니다: {exc}")

    for note in notes:
        say(note)
    return StageResult(events=list(events), notes=notes,
                       extra={"terms": terms, "summary": summarize(terms)})


# ---------------------------------------------------------------- 단계 ② 한국어 교정

def stage_korean(events: list[Event], profile: dict | None = None, *,
                 corrector_path: str | None = None, backend=None,
                 spacing_mode: str = "principle",
                 progress: Progress | None = None) -> StageResult:
    """한국어 교정기를 붙인다. 자막 문법은 교정기에 넘기지 않는다(`korean.py`).

    **교정기를 못 찾으면 예외를 올리지 않고 `notes`에 적어 돌려준다.** 어댑터가 그
    사실을 사용자에게 보이면 되고, 나머지 단계는 계속 돌아야 한다.

    `backend`를 넘기면 그것을 쓴다. 형태소 분석기 적재가 1~2분이라 **파일마다 다시
    올리면 그 비용이 파일 수만큼 곱해진다** — 여러 파일을 도는 어댑터는 한 번 올려
    넘긴다.
    """
    say = progress or _silent
    if backend is None:
        try:
            say("한국어 교정기를 부릅니다...")
            backend = load_backend(corrector_path)
        except CorrectorUnavailable as exc:
            return StageResult(events=list(events),
                               notes=[f"한국어 교정 레인 건너뜀: {exc}"])

    fixed, violations = run_korean_pass(events, backend, spacing_mode=spacing_mode,
                                       profile=profile)
    edits = _edits(events, fixed)
    return StageResult(events=list(fixed), changed=len(edits),
                       violations=[v.to_dict() for v in violations],
                       extra={"edits": edits})


# ---------------------------------------------------------------- 단계 ③ 규정 자동교정

def stage_fixes(events: list[Event], profile: dict, *, job_rules=None,
                progress: Progress | None = None) -> StageResult:
    """규정이 정답을 하나로 정해 주는 것만 자동으로 고친다."""
    say = progress or _silent
    say("규정 자동 교정 중...")
    fixed, applied, unfixable = apply_fixes(events, profile, job_rules)
    edits = _edits(events, fixed)
    return StageResult(events=list(fixed), changed=len(edits),
                       extra={"applied": applied, "unfixable": unfixable,
                              "edits": edits})


# ---------------------------------------------------------------- 단계 ④ 규정 검사

def stage_check(events: list[Event], profile: dict, *, children: bool = False,
                fps: float | None = None, busy_spans=None, job_rules=None,
                progress: Progress | None = None) -> StageResult:
    """규정 위반을 센다. **반드시 마지막이다** — 리포트는 최종 자막을 설명해야 한다."""
    say = progress or _silent
    say("검사 중...")
    report = check_events([e.__dict__ for e in events], profile, children=children,
                          fps=fps, busy_spans=busy_spans, job_rules=job_rules)
    return StageResult(events=list(events), violations=list(report["violations"]),
                       extra={"report": report})


# ---------------------------------------------------------------- 이어 붙이기

@dataclass
class CorrectOptions:
    """`correct_and_check`의 설정. 어댑터가 자기 설정을 이것으로 옮겨 넘긴다."""

    korean: bool = False
    corrector_path: str | None = None
    backend: object | None = None       # 이미 올린 교정기를 물려준다(적재 비용 절약)
    # **교정문을 자막에 얹을지.** 끄면 지적만 모으고 글자는 그대로 둔다. 파일을 쓰지
    # 않는 검사에서 필요하다 — 얹어 놓고 검사하면 리포트가 사용자가 가진 자막이
    # 아니라 "고쳤다면 됐을 것"을 설명하게 된다.
    apply_korean: bool = True
    spacing_mode: str = "principle"
    apply_fixes: bool = True
    children: bool = False
    fps: float | None = None
    busy_spans: list | None = None
    job_rules: object | None = None


def correct_and_check(events: list[Event], profile: dict, options: CorrectOptions,
                      progress: Progress | None = None) -> StageResult:
    """②③④를 정해진 순서로 잇는다. **모든 어댑터가 이 함수를 부른다.**

    돌려주는 `StageResult`의 `events`가 사용자에게 나갈 자막이고, `violations`가 그
    자막을 설명하는 리포트다. 둘이 어긋나지 않는 것이 이 함수의 존재 이유다.
    """
    say = progress or _silent
    notes: list[str] = []
    korean_violations: list[dict] = []
    current = list(events)
    korean_changed = fix_changed = 0

    korean_edits: list[dict] = []
    fix_edits: list[dict] = []

    if options.korean:
        result = stage_korean(current, profile, corrector_path=options.corrector_path,
                              backend=options.backend,
                              spacing_mode=options.spacing_mode, progress=say)
        korean_violations = result.violations
        notes += result.notes
        if options.apply_korean:
            current, korean_changed = result.events, result.changed
            korean_edits = result.extra.get("edits", [])

    applied = unfixable = None
    if options.apply_fixes:
        result = stage_fixes(current, profile, job_rules=options.job_rules, progress=say)
        current, fix_changed = result.events, result.changed
        applied, unfixable = result.extra["applied"], result.extra["unfixable"]
        fix_edits = result.extra["edits"]

    checked = stage_check(current, profile, children=options.children, fps=options.fps,
                          busy_spans=options.busy_spans, job_rules=options.job_rules,
                          progress=say)

    # 한국어 교정이 낸 확인 항목을 규정 위반과 한 목록으로 합친다. 사용자는 출처가
    # 어디든 "고쳐야 할 것"을 한 번에 본다 — 정렬 기준은 자막 번호다.
    violations = checked.violations + korean_violations
    violations.sort(key=lambda v: (v["event_index"], v["rule_id"]))

    return StageResult(
        events=current,
        notes=notes,
        violations=violations,
        changed=sum(1 for a, b in zip(events, current) if a.text != b.text),
        extra={"report": checked.extra["report"], "applied": applied,
               "unfixable": unfixable, "korean_changed": korean_changed,
               "fix_changed": fix_changed,
               # 처음 것과 마지막 것을 견주어 낸다. 두 단계의 목록을 이어 붙이면
               # 같은 줄이 두 번 나오고, 한국어 교정이 넣은 글자를 규정 교정이 다시
               # 걷어낸 자리는 '바뀌었다'고 잘못 적힌다.
               "edits": _edits(events, current),
               "korean_edits": korean_edits, "fix_edits": fix_edits},
    )


# ---------------------------------------------------------------- 단계 목록

@dataclass(frozen=True)
class Stage:
    """화면이 읽는 단계 선언. **UI가 이 목록을 렌더링만 하게 하려고 있다.**

    `requires`가 있으면 그 단계가 끝나야 이 단계를 켠다. `why_not`이 그 이유를
    문장으로 돌려주므로 안내 문구가 화면 코드에 흩어지지 않는다 — 지금은 같은 문구가
    `app/window.py`의 세 곳에 복사돼 있다.
    """

    id: str
    label: str
    requires: tuple[str, ...] = ()
    needs_video: bool = False
    note: str = ""

    def available(self, *, has_subtitle: bool, has_video: bool = False,
                  done: set[str] | None = None) -> tuple[bool, str]:
        """켤 수 있는가, 아니면 **왜 안 되는가**.

        이유를 여기서 문장으로 돌려주는 것이 요점이다. 지금은 같은 안내가
        `app/window.py`의 세 곳(502·522·545행)에 복사돼 있어, 단계를 하나 늘리면
        세 곳을 고쳐야 한다.
        """
        if self.needs_video and not has_video:
            return False, "영상이 필요합니다. [영상 열기]로 영상을 여세요."
        if not self.needs_video and not has_subtitle:
            return False, ("자막이 없습니다. [① 자막 만들기]로 만들거나 "
                           "[자막 열기]로 여세요.")
        missing = [r for r in self.requires if r not in (done or set())]
        if missing:
            labels = [s.label for s in STAGES if s.id in missing]
            return False, f"먼저 끝내야 합니다: {', '.join(labels)}"
        return True, ""


# 화면에 이 순서로, 이 번호로 보인다. 번역·번역 QA는 여기 한 줄씩 더하면 된다.
#
# `needs_video`가 참인 단계는 영상이 있어야 켜진다. 나머지는 자막만 있으면 된다 —
# 작업자가 이미 만들어진 자막을 받아 교정만 하는 경우가 실무에서 가장 흔하다
# (`CLAUDE.md` §8).
STAGES: tuple[Stage, ...] = (
    Stage("generate", "① 자막 만들기", needs_video=True,
          note="영상에서 전사·타임코드·초벌 자막을 만든다. **교정은 하지 않는다** — "
               "초안을 사람이 먼저 보게 한다."),
    Stage("korean", "② 한국어 교정",
          note="맞춤법·띄어쓰기를 국립국어원 근거로 본다. 자동 교정과 확인 항목이 갈린다."),
    Stage("check", "③ 규정 검사",
          note="발주처 규정 위반을 센다. 자막이 바뀌면 다시 돌려야 한다."),
    Stage("translate", "번역",
          note="원어를 한국어 초벌로 옮긴다. **타임코드를 건드리지 않는다** — "
               "시각이 이미 잡힌 원어 자막을 받았으면 [자막 열기]로 열고 이것을 "
               "쓰면 된다. 전사를 통째로 건너뛴다."),
    Stage("terms", "용어표",
          note="대본에서 고유명사·약어를 뽑아 조사한다. 자막을 바꾸지 않는다."),
)


def stage_by_id(stage_id: str) -> Stage | None:
    return next((s for s in STAGES if s.id == stage_id), None)
