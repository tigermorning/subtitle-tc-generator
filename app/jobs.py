"""오래 걸리는 일을 다른 실에서 돌린다.

전사·번역·검사는 몇 초에서 몇 분까지 간다. 화면이 그 동안 멈추면 쓸 수 없다.

**여기서 일을 하지 않는다.** 전부 `checker/`를 부른다. 이 파일이 하는 일은 진행
상황을 화면에 흘려보내고, 끝났을 때 결과를 넘기는 것뿐이다. 규칙이 두 벌이 되면
반드시 어긋난다.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from .log import write as log


class Job(QObject):
    """일 하나. `run()`을 다른 실에서 부른다."""

    message = Signal(str)
    failed = Signal(str)
    finished = Signal(object)

    def say(self, text: str) -> None:
        """진행 상황. 화면과 로그에 함께 남긴다."""
        log(text)
        self.message.emit(text)

    def run(self) -> None:                       # 자식이 채운다
        raise NotImplementedError

    def _guarded(self, work) -> None:
        log(f"{type(self).__name__} 시작")
        try:
            result = work()
            log(f"{type(self).__name__} 끝")
            self.finished.emit(result)
        except Exception as exc:
            import traceback
            log(f"{type(self).__name__} 실패: {traceback.format_exc()}")
            # **조용히 죽지 않는다.** 왜 멈췄는지 화면에 남는다.
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class GenerateJob(Job):
    """영상에서 자막을 만든다. 결과는 Event 목록."""

    def __init__(self, video: Path, profile: dict, script: Path | None,
                 language: str, translate: bool, speech: str = "auto"):
        super().__init__()
        self.video, self.profile, self.script = video, profile, script
        self.language, self.translate, self.speech = language, translate, speech

    def run(self) -> None:
        def work():
            from checker.generate import generate
            translator = None
            if self.translate:
                from checker.translate import make_translator
                translator = make_translator()
            draft = generate(self.video, self.profile, script=self.script,
                             language=self.language, translator=translator,
                             speech_method=self.speech,
                             progress=self.say)
            return draft
        self._guarded(work)


class CheckJob(Job):
    """규정·한국어 검사. 결과는 (교정된 자막, 위반 목록)."""

    def __init__(self, events, profile: dict, fix: bool, korean: bool,
                 corrector_path: str | None, job_rules=None):
        super().__init__()
        self.events, self.profile, self.fix = events, profile, fix
        self.korean, self.corrector_path, self.job_rules = korean, corrector_path, job_rules

    def run(self) -> None:
        def work():
            from checker.model import Event
            from checker.pipeline import CorrectOptions, correct_and_check

            events = [Event(e.index, e.start_ms, e.end_ms, e.text) for e in self.events]
            # 단계 순서를 여기서 정하지 않는다 — `pipeline`이 정한다. 전에는 이 파일이
            # 자기 순서를 갖고 있어서 SE 플러그인과 다른 리포트가 나왔다. 그리고
            # **한국어 위반을 버리고 있었다**(`events, _ = run_korean_pass`) — 그래서
            # 화면에 한국어 확인 항목이 한 건도 뜨지 않았다.
            result = correct_and_check(
                events, self.profile,
                CorrectOptions(
                    korean=bool(self.korean and self.corrector_path),
                    corrector_path=self.corrector_path,
                    apply_fixes=bool(self.fix),
                    job_rules=self.job_rules,
                ),
                progress=self.say,
            )
            for note in result.notes:
                self.say(note)
            return result.events, result.violations
        self._guarded(work)


class TranslateJob(Job):
    """한국어로 옮긴다. **타임코드는 건드리지 않는다.**"""

    def __init__(self, events, profile: dict, passes: int, knp: Path | None):
        super().__init__()
        self.events, self.profile, self.passes, self.knp = events, profile, passes, knp

    def run(self) -> None:
        def work():
            from checker.model import Event
            from checker.translate import (Glossary, make_translator, to_events,
                                           translate_events)

            translator = make_translator()
            glossary = Glossary.from_profile(self.profile)
            if self.knp:
                added = glossary.merge_knp(self.knp)
                self.say(f"KNP에서 용어 {added}개")

            source = [Event(e.index, e.start_ms, e.end_ms, e.text) for e in self.events]
            cues = translate_events(source, translator, glossary,
                                    progress=self.say)
            events = to_events(cues, source)

            if self.passes > 1:
                from checker.revise import revise
                original = {e.index: e.text for e in source}
                for stage in ("2차", "3차")[:self.passes - 1]:
                    events, _ = revise(events, translator, source=original,
                                       glossary=glossary, stage=stage,
                                       progress=self.say)
            return events
        self._guarded(work)


class TermsJob(Job):
    """용어를 뽑아 조사한다. 결과는 (용어 목록, 저장한 파일)."""

    def __init__(self, events, out: Path, web: bool, explain: bool,
                 corrector_path: str | None, knp: Path | None):
        super().__init__()
        self.events, self.out, self.web = events, out, web
        self.explain, self.corrector_path, self.knp = explain, corrector_path, knp

    def run(self) -> None:
        def work():
            from checker.terms import extract, research, to_tsv

            terms = extract([e.text for e in self.events])
            self.say(f"용어 후보 {len(terms)}개")

            lookup = None
            if self.corrector_path:
                try:
                    from checker.cli import _loanword_lookup
                    lookup = _loanword_lookup(Path(self.corrector_path))
                except Exception as exc:
                    self.say(f"규범 용례 조회를 건너뜁니다: {exc}")

            glossary = {}
            if self.knp:
                from checker.knp import read_terms
                glossary = read_terms(self.knp)

            research(terms, lookup=lookup, glossary=glossary, web=self.web,
                     progress=self.say)

            if self.explain:
                try:
                    from checker.terms import explain
                    from checker.translate import make_translator
                    explain(terms, make_translator(), progress=self.say)
                except Exception as exc:
                    self.say(f"용어 설명을 건너뜁니다: {exc}")

            self.out.write_text(to_tsv(terms), encoding="utf-8-sig")
            return terms, self.out
        self._guarded(work)


# 돌고 있는 실과 **일 객체**를 여기서 붙잡는다. 아래 이유로 둘 다 필요하다.
_ALIVE: list[tuple[QThread, "Job"]] = []


def start(job: Job, on_done, on_message, on_failed) -> QThread:
    """일을 다른 실에서 시작한다.

    **실과 일 객체를 둘 다 붙잡아야 한다.** 실만 붙잡으면 파이썬이 `Job`을 거둬 가고,
    그러면 `thread.started`에 연결한 슬롯이 사라져 **아무 일도 없이 조용히 끝난다** —
    예외도, `failed` 신호도 없다. `moveToThread`는 소유권을 넘기지 않는다.

    2026-08-12 실사용에서 이것이 실제로 났다. [자막 만들기]를 누르면 상태줄이
    "만드는 중입니다..."에서 16분간 멈춰 있었고, 로그에 한 줄도 안 늘고, ffprobe·
    ffmpeg·ollama 어느 것도 뜨지 않고, CPU는 10초에 0.5초만 썼다. 부르는 쪽
    (`window._start`)이 `job`을 지역 변수로 두고 실만 보관했기 때문이다.

    끝나면 목록에서 뺀다 — 안 그러면 오래 쓰는 동안 계속 쌓인다.
    """
    thread = QThread()
    job.moveToThread(thread)
    thread.started.connect(job.run)
    job.finished.connect(on_done)
    job.message.connect(on_message)
    job.failed.connect(on_failed)
    job.finished.connect(thread.quit)
    job.failed.connect(thread.quit)

    held = (thread, job)
    _ALIVE.append(held)

    def _release() -> None:
        # 실이 실제로 끝난 뒤에 놓는다. `finished` 신호에서 바로 놓으면 실이 아직
        # 정리 중이라 같은 사고가 다시 난다.
        if held in _ALIVE:
            _ALIVE.remove(held)

    thread.finished.connect(_release)
    thread.start()
    return thread
