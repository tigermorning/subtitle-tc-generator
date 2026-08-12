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
                from checker.translate import ensure_server, make_translator
                # 여기서는 **기다린다.** 어차피 몇 분 걸리는 일이라 몇 초는 싸다.
                ensure_server(progress=self.say, wait_seconds=20)
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
    """한국어로 옮긴다. **타임코드는 건드리지 않는다.**

    순서와 회차는 `pipeline`이 정한다. 전에는 이 클래스가 자기 순서를 적어 두어
    세 가지가 CLI와 달랐다 — 사용자의 번역 모델 설정을 무시했고, 감수 내역을 버려
    무엇이 바뀌었는지 볼 수 없었고, 타임코드 고정을 확인하지 않았다.
    """

    def __init__(self, events, profile: dict, passes: int, knp: Path | None,
                 model: str | None = None, cast: dict | None = None,
                 work_beside: Path | None = None):
        super().__init__()
        self.events, self.profile, self.passes, self.knp = events, profile, passes, knp
        self.model, self.cast = model, cast
        # **여기가 원래 아무것도 남기지 않던 곳이다.** 15분 걸린 번역이 3차에서
        # 깨지면 처음부터 해야 했다.
        self.work_beside = work_beside

    def run(self) -> None:
        def work():
            from checker.model import Event
            from checker.pipeline import stage_revise, stage_translate
            from checker.translate import Glossary, ensure_server, make_translator

            ensure_server(progress=self.say, wait_seconds=20)
            translator = make_translator(self.model)
            glossary = Glossary.from_profile(self.profile)
            if self.knp:
                added = glossary.merge_knp(self.knp)
                self.say(f"KNP에서 용어 {added}개")

            work = None
            if self.work_beside:
                from checker.work import Work
                work = Work.beside(self.work_beside)
                work.save_source({e.index: e.text for e in self.events})
                self.say(f"단계별 결과를 남깁니다: {work.root.name}")

            source = [Event(e.index, e.start_ms, e.end_ms, e.text) for e in self.events]
            first = stage_translate(source, self.profile, translator=translator,
                                    glossary=glossary, progress=self.say)
            if work:
                work.save("02-first", first.events, model=translator.model,
                          extra={"flags": len(first.extra.get("flags") or [])})
            # 타임코드가 움직였으면 쓰지 않는다. 조용히 넘기면 사람은 고정된 줄 알고
            # 기계는 옮긴 상태로 납품물이 나간다.
            if first.violations:
                raise RuntimeError(first.violations[0]["message"])

            events, revisions = first.events, []
            if self.passes > 1:
                later = stage_revise(events, self.profile, translator=translator,
                                     source={e.index: e.text for e in source},
                                     glossary=glossary, rounds=self.passes - 1,
                                     cast=self.cast,
                                     on_round=((lambda label, role, evs, changed:
                                                work.save(f"03-revise-{label}", evs,
                                                          model=translator.model,
                                                          extra={"changed": changed,
                                                                 "role": role}))
                                               if work else None),
                                     progress=self.say)
                events, revisions = later.events, later.extra["revisions"]
                for row in later.extra["rounds"]:
                    self.say(f"{row['stage']}({row['role']}) {row['changed']}곳 고침")
                # 상한에 걸린 것과 다 끝난 것을 구분해서 보인다.
                self.say(later.extra["stopped_because"])

            return events, first.extra["notes_by_index"], revisions
        self._guarded(work)


class ReviseJob(Job):
    """이미 번역된 자막을 감수·윤문한다. 결과는 (자막, 바뀐 내역, 멈춘 이유).

    **1차 번역과 갈라 놓았다.** 한 버튼이 1차부터 3차까지 다 하면 단계 사이에 사람이
    검토할 자리가 없다 — 사용자 요구가 "단계를 독립적으로 돌리고 사이에 검토"였다.
    """

    def __init__(self, events, profile: dict, sources: dict, rounds: int,
                 first_role: str = "감수", knp: Path | None = None,
                 model: str | None = None, cast: dict | None = None,
                 work_beside: Path | None = None, step_prefix: str = "03-revise"):
        super().__init__()
        self.events, self.profile, self.sources = events, profile, sources
        self.rounds, self.first_role = rounds, first_role
        self.knp, self.model, self.cast = knp, model, cast
        self.work_beside, self.step_prefix = work_beside, step_prefix

    def run(self) -> None:
        def work():
            from checker.model import Event
            from checker.pipeline import stage_revise
            from checker.translate import Glossary, ensure_server, make_translator

            ensure_server(progress=self.say, wait_seconds=20)
            translator = make_translator(self.model)
            glossary = Glossary.from_profile(self.profile)
            if self.knp:
                self.say(f"KNP에서 용어 {glossary.merge_knp(self.knp)}개")

            work = None
            if self.work_beside:
                from checker.work import Work
                work = Work.beside(self.work_beside)

            events = [Event(e.index, e.start_ms, e.end_ms, e.text) for e in self.events]
            result = stage_revise(
                events, self.profile, translator=translator, source=self.sources,
                glossary=glossary, rounds=self.rounds, first_role=self.first_role,
                cast=self.cast,
                on_round=((lambda label, role, evs, changed:
                           work.save(f"{self.step_prefix}-{label}", evs,
                                     model=translator.model,
                                     extra={"changed": changed, "role": role}))
                          if work else None),
                progress=self.say)
            for row in result.extra["rounds"]:
                self.say(f"{row['stage']}({row['role']}) {row['changed']}곳 고침")
            self.say(result.extra["stopped_because"])
            return (result.events, result.extra["revisions"],
                    result.extra["stopped_because"])
        self._guarded(work)


class PolishJob(Job):
    """③ 자막 윤문·QA. 결과는 (자막, 위반, 바뀐 내역).

    **순서를 여기서 정하지 않는다.** `stage_polish`가 윤문 -> 한국어 교정 -> 규정 검사를
    잇는다 — 전에 이 파일이 자기 순서를 갖고 있어서 CLI와 갈라졌다.
    """

    def __init__(self, events, profile: dict, sources: dict,
                 corrector_path: str | None = None, knp: Path | None = None,
                 model: str | None = None, cast: dict | None = None,
                 job_rules=None, work_beside: Path | None = None):
        super().__init__()
        self.events, self.profile, self.sources = events, profile, sources
        self.corrector_path, self.knp = corrector_path, knp
        self.model, self.cast, self.job_rules = model, cast, job_rules
        self.work_beside = work_beside

    def run(self) -> None:
        def work():
            from checker.model import Event
            from checker.pipeline import stage_polish
            from checker.translate import Glossary, ensure_server, make_translator

            ensure_server(progress=self.say, wait_seconds=20)
            translator = make_translator(self.model)
            glossary = Glossary.from_profile(self.profile)
            if self.knp:
                self.say(f"KNP에서 용어 {glossary.merge_knp(self.knp)}개")

            keep = None
            if self.work_beside:
                from checker.work import Work
                keep = Work.beside(self.work_beside)

            events = [Event(e.index, e.start_ms, e.end_ms, e.text) for e in self.events]
            result = stage_polish(
                events, self.profile, translator=translator, source=self.sources,
                glossary=glossary, cast=self.cast, korean=bool(self.corrector_path),
                corrector_path=self.corrector_path, job_rules=self.job_rules,
                on_round=((lambda label, role, evs, changed:
                           keep.save(f"04-polish-{label}", evs,
                                     model=translator.model,
                                     extra={"changed": changed, "role": role}))
                          if keep else None),
                progress=self.say)
            for note in result.notes:
                self.say(note)
            if keep:
                keep.save("05-final", result.events,
                          extra={"violations": len(result.violations)})
            return result.events, result.violations, result.extra["revisions"]
        self._guarded(work)


class CharactersJob(Job):
    """캐릭터 분석 문서를 만든다. 결과는 (인물 목록, 집계, 표 경로, 문서 경로).

    **KNP 시트와 다른 문서다.** 외부 조사는 `wiki`를 줄 때만 돈다 — 나가는 것은
    작품 제목과 인물 이름뿐이고 대사는 어떤 경우에도 나가지 않는다.
    """

    def __init__(self, events, out: Path, wiki: str = "", work_title: str = "",
                 limit: int = 0):
        super().__init__()
        self.events, self.out = events, out
        self.wiki, self.work_title, self.limit = wiki, work_title, limit

    def run(self) -> None:
        def work():
            from checker import characters

            from checker.pipeline import stage_characters

            result = stage_characters(self.events, wiki=self.wiki,
                                      work_title=self.work_title, limit=self.limit,
                                      progress=self.say)
            people, counts = result.extra["people"], result.extra["counts"]
            for note in result.notes:
                self.say(note)
            md = self.out.with_suffix(".md")
            self.out.write_text(characters.to_tsv(people), encoding="utf-8-sig")
            md.write_text(characters.to_markdown(people, counts, self.work_title),
                          encoding="utf-8")
            return people, counts, self.out, md
        self._guarded(work)


class TermsJob(Job):
    """용어를 뽑아 조사한다. 결과는 (용어 목록, 저장한 파일)."""

    def __init__(self, events, out: Path, web: bool, explain: bool,
                 corrector_path: str | None, knp: Path | None,
                 model: str | None = None):
        super().__init__()
        self.events, self.out, self.web = events, out, web
        self.explain, self.corrector_path, self.knp = explain, corrector_path, knp
        self.model = model

    def run(self) -> None:
        def work():
            from checker.pipeline import stage_terms
            from checker.terms import to_tsv

            translator = None
            if self.explain:
                from checker.translate import make_translator
                try:
                    translator = make_translator(self.model)
                except Exception as exc:
                    self.say(f"용어 설명을 건너뜁니다: {exc}")

            result = stage_terms(self.events, corrector_path=self.corrector_path,
                                 knp=self.knp, web=self.web, translator=translator,
                                 progress=self.say)
            terms = result.extra["terms"]
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
