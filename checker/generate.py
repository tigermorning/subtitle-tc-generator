"""빈칸을 태운다 — 영상(과 스크립트)에서 자막 초안을 만든다.

지금까지의 모듈들은 **사람이 이미 쓴 자막을 검사**했다. 이 모듈은 그 앞 단계다.
영상을 넣으면 자막이 나온다.

    SDH        영상            -> 전사 -> 재분할 -> 스포팅 -> 초안
    번역 자막   영상 + 원어 스크립트 -> 전사 -> 스크립트 대조 -> 재분할 -> 스포팅 -> 초안

**초안이다.** 사람이 고칠 것을 전제로 만든다. 그래서 기계가 자신 없는 자리를
지우지 않고 남긴다 — `notes.srt`로 따로 내보내 SE에서 원본 옆에 띄워 볼 수 있다.

**단계를 섞지 않는다.** 전사는 글자 수를 무시하고 자유롭게, 재단은 그 뒤에.
(왜인지는 `resplit.py` 첫머리에 적어 두었다.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .align import AlignedCue, Segment, align, summary
from .media import find_speech, probe
from .model import Event
from .resplit import resplit_all
from .timing import TimingLimits, converge


@dataclass
class Draft:
    events: list[Event]
    notes: list[tuple[int, str]] = field(default_factory=list)  # (자막 번호, 봐야 할 이유)
    stats: dict = field(default_factory=dict)
    # 자막 번호 -> 원어. 번역했다면 번역 전 글자를 남긴다. **자막은 두 벌이다.**
    sources: dict[int, str] = field(default_factory=dict)
    # 2차·3차에서 바뀐 내역. `passes`가 1이면(기본) 비어 있다.
    revisions: list = field(default_factory=list)


# 대본의 화자 표시. `SARAH:`, `Mrs. Kim:`, `철수:` 꼴을 잡는다. 대사 안의 콜론
# (`9:30`, `이유는: 없다`)과 섞이지 않게 **줄 맨 앞**에서만, 짧은 이름만 본다.
# 이름은 최대 세 낱말, 숫자로 끝나지 않고, 콜론 뒤가 숫자여도 안 된다.
# `He said 9:30, not 10.`에서 "He said 9"를 이름으로 잘못 잡아 시각을 잘라 먹었다.
SPEAKER_PREFIX = re.compile(
    r"^\s*((?:[A-Z][A-Za-z.'\-]*)(?:\s+[A-Z][A-Za-z.'\-]*){0,2}|[가-힣]{1,8})\s*:\s*(?=[^\d\s])")
# 지문·괄호 설명. 통째로 괄호인 줄은 대사가 아니다.
STAGE_DIRECTION = re.compile(r"^[\(\[][^)\]]*[\)\]]$")


@dataclass
class ScriptLine:
    speaker: str
    text: str


def read_script(path: Path) -> list[ScriptLine]:
    """원어 스크립트를 대사 단위로 읽는다.

    대본은 형식이 제각각이라 한 줄이 곧 한 대사는 아니다. 빈 줄로 나뉜 덩어리를
    문단으로 보고, 문단 안의 줄바꿈은 이어 붙인다 — 대본의 줄바꿈은 종이 폭 때문에
    생긴 것이지 대사가 끊긴 자리가 아니다.

    **화자 표시와 지문은 대사에서 떼어 낸다.** 작업자 자료 100행: "스크립트에
    있다고 무조건 사용은 금물! 스크립트에서는 대사만 딸 것!" 떼지 않으면 `SARAH:`가
    그대로 자막에 실려 나간다 — 실제로 그렇게 나갔다(2026-08-11).

    떼되 **버리지는 않는다.** SDH에서는 화자명이 필요하고, 대본이 그것을 알고 있는
    유일한 자리다.
    """
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    lines: list[ScriptLine] = []
    for block in text.split("\n\n"):
        joined = " ".join(l.strip() for l in block.split("\n") if l.strip()).strip()
        if not joined or STAGE_DIRECTION.match(joined):
            continue           # 지문은 대사가 아니다
        speaker = ""
        found = SPEAKER_PREFIX.match(joined)
        if found:
            speaker = found.group(1).strip()
            joined = joined[found.end():].strip()
            # 대본은 화자명을 대문자로 적는다. 자막에 그대로 쓰지 않는다.
            if speaker.isupper():
                speaker = speaker.title()
        if joined:
            lines.append(ScriptLine(speaker, joined))
    return lines


def speaker_prefix(name: str, profile: dict) -> str:
    """플랫폼 표기로 화자명을 만든다. 번역 자막에서는 쓰지 않는다."""
    if not name:
        return ""
    enclosure = ((profile.get("speaker_id") or {}).get("enclosure") or "[]")
    left, right = (enclosure + "[]")[:2]
    return f"{left}{name}{right} "


def generate(video: Path, profile: dict, script: Path | None = None,
             language: str = "auto", model: str | None = None,
             fps: float | None = None, use_gpu: bool = True,
             keep_transcript: Path | None = None, translator=None,
             glossary=None, keep_source: Path | None = None,
             speech_method: str = "auto", diarize: bool = False,
             passes: int = 1, max_passes: int = 0, settle_at: int = 0,
             cast: dict[str, str] | None = None,
             transcript_cache: Path | None = None,
             progress=None) -> Draft:
    """영상에서 자막 초안을 만든다.

    `translator`를 주면 원어를 한국어로 옮긴다. **번역이 먼저, 재분할이 나중이다** —
    원어 기준으로 끊어 놓으면 한국어가 거기에 갇힌다(사용자 지적).

    `passes`가 1보다 크면 1차 뒤에 2차·3차(감수·윤문)도 돈다 — **재분할보다
    먼저다.** 둘 다 "③ 번역" 안의 하위 단계이기 때문이다(`revise.py` 첫머리
    — 1차·2차·3차 전부 번역 단계다, `regroup.py`가 아니다). 재분할 뒤에 돌면
    3차가 만든 최종 글자 수가 아니라 1차의 투박한 글자 수로 자막을 나누게
    된다.

    **실측(2026-08-27)**: `--generate --passes 3`가 조용히 1차만 돌고
    2차·3차를 건너뛴 적이 있다 — `--passes`가 `--generate`가 아닌 다른 모드
    (받은 TC에 번역만 얹는 경로)에만 연결돼 있었다. 이 함수 자체에 붙여서
    다시는 그 경로 분기에 좌우되지 않게 한다.

    `transcript_cache`를 주면 whisper 전사를 캐시에서 재사용한다(있으면 읽고,
    없으면 전사 후 만든다) — `checker.transcribe.transcribe()`의 `cache`와 같다.
    같은 영상을 상한값 재조정 등으로 여러 번 다시 돌릴 때 쓴다.
    """
    from .transcribe import transcribe   # ffmpeg이 없어도 이 모듈은 import 되게

    say = progress or (lambda _m: None)
    video = Path(video)

    media = probe(video)
    if fps is None:
        fps = media.fps or 23.976
    say(f"영상: {media.duration_ms / 1000:.0f}초, {fps:.3f}fps")

    # 말소리 구간을 전사보다 먼저 찾는다. 완전한 침묵(로고·크레딧 구간)에서
    # whisper가 같은 말을 반복하는 환각을 내는 것을 걸러내려면 전사 직후에
    # 말소리 위치가 있어야 한다(아래 필터링 참고).
    speech, how = find_speech(video, method=speech_method,
                              duration_ms=media.duration_ms, progress=say)
    say(f"말소리 구간 {len(speech)}개 ({'모델' if how == 'vad' else '음량'})")

    segments = transcribe(video, language=language, model=model,
                          use_gpu=use_gpu, progress=say, keep=keep_transcript,
                          cache=transcript_cache)
    if not segments:
        return Draft([], [], {"transcript": 0})

    # **말소리 구간과 전혀 안 겹치는 조각은 뺀다.** whisper는 완전한 침묵에서도
    # 자신 있게 글자를 만들어 낸다 — 흔한 실패 모드다(2026-08-26, 영화D·영화F
    # and Monsters 두 영화의 오프닝 로고 구간에서 밀리초까지 같은 타임스탬프에
    # "네! 네! 네!"·"헤이 헤이 헤이" 같은 반복이 나온 것으로 확인). 실제 말소리가
    # 조금이라도 있으면 VAD가 잡으므로, 겹치는 구간이 하나도 없는 조각은 소리가
    # 아니라 지어낸 것으로 본다. 지우지 않고 세어서 알린다(추정 자동 삭제가
    # 아니라 근거 있는 필터임 — 규칙 4).
    #
    # **VAD의 오디오 읽기 자체가 도중에 멎을 수 있다.** 컨테이너 손상 등으로
    # ffmpeg이 오디오를 끝까지 못 읽으면 `speech`가 영상 길이보다 훨씬 짧게
    # 끝난다 — 그 뒤는 "침묵"이 아니라 "검출을 못 한 구간"이다. 실측(2026-08-27,
    # 예능A 15회): VAD는 3113초에서 멎었는데 whisper 전사는 3478초까지
    # 멀쩡했다. 이 구분 없이 필터를 걸었더니 **실제 대사가 있는 마지막 6분이
    # 통째로 삭제되는 사고**가 났다 — 막으려던 문제(침묵 환각)보다 더 큰 손실이라
    # 반드시 갈라야 한다.
    if speech:
        speech_end = max(e for _, e in speech)
        coverage_gap = media.duration_ms - speech_end
        # 30초는 여유값이다. 진짜 무음 엔딩(크레딧 등)은 이보다 짧은 게 보통이고,
        # 몇 분 단위로 벌어지면 검출 자체가 멎었다고 본다.
        undetected_after = coverage_gap > 30_000

        if undetected_after:
            say(f"말소리 검출이 영상 끝보다 {coverage_gap / 1000:.0f}초 일찍 "
                "멎었습니다 — 그 뒤는 침묵으로 보지 않고 그대로 둡니다"
                "(검출 자체가 못 미쳤을 수 있습니다)")

        def _has_speech(seg) -> bool:
            if undetected_after and seg.start_ms >= speech_end:
                return True   # 검출이 못 미친 구간 — 걸러내지 않는다
            return any(s < seg.end_ms and seg.start_ms < e for s, e in speech)

        kept = [s for s in segments if _has_speech(s)]
        dropped = len(segments) - len(kept)
        if dropped:
            say(f"말소리와 전혀 안 겹치는 전사 조각 {dropped}개를 뺐습니다"
                " — 침묵에서 whisper가 지어낸 것으로 보입니다")
        segments = kept
        if not segments:
            return Draft([], [], {"transcript": 0})

    notes: list[tuple[int, str]] = []
    stats: dict = {"transcript": len(segments)}

    if script:
        # 대본은 워드·PDF로도 온다. 형식은 `script.py`가 가린다.
        from .script import read_lines
        script_lines = read_lines(Path(script))
        say(f"스크립트 {len(script_lines)}줄과 대조합니다")

        # **대본이 화자명을 주면 우리 표기로 남긴다.** 원문이 `화자1:`로 적었든
        # `SARAH:`로 적었든 자막은 `[화자1]`이다(사용자 지적 2026-08-11).
        # 원문 표기는 번역 과정에서만 쓰이고 납품물에 실리지 않는다.
        #
        # 번역 자막의 말자막에 화자명을 두는지는 작업마다 다르지만, 초벌에 남겨
        # 두는 편이 안전하다 — 빼는 것은 한 번에 되고, 없는 것을 되살리려면
        # 대본을 다시 봐야 한다.
        named = sum(1 for l in script_lines if l.speaker)
        if named:
            say(f"대본에서 화자명 {named}개를 찾아 "
                f"{profile.get('platform')} 표기로 붙입니다")
        lines = [speaker_prefix(l.speaker, profile) + l.text for l in script_lines]
        cues = align(segments, lines)
        stats.update(summary(cues))
        events = _to_events(cues, notes)
    else:
        # **전사 조각을 자막 단위로 다시 묶는다.** whisper는 말이 잠깐 멎을 때마다
        # 끊지만 사람은 한 호흡을 한 자막에 담는다(`regroup.py` 첫머리에 근거를
        # 적어 두었다 — 전문가 타임코드와 대조해 값을 골랐다).
        #
        # 대본이 있으면 하지 않는다. 그때는 대본의 줄이 곧 자막 단위다.
        from .regroup import limits_from_profile, merge_cues
        raw = [Event(i, s.start_ms, s.end_ms, s.text) for i, s in enumerate(segments, 1)]
        max_ms, max_gap = limits_from_profile(profile)

        speaker_turns = None
        if diarize:
            from .diarize import find_speaker_turns
            speaker_turns = find_speaker_turns(video, progress=say)

        events = merge_cues(raw, max_ms, max_gap, speaker_turns=speaker_turns)
        if len(events) != len(raw):
            say(f"전사 조각 {len(raw)}개를 자막 {len(events)}개로 묶었습니다")
        if profile.get("kind") == "sdh":
            # **화자명은 대본에서 온다.** `--diarize`를 켜도 마찬가지다 — 화자
            # 분리는 "1번 화자와 2번 화자가 다른 사람"까지만 알려 주고, 그 사람이
            # 누구인지(이름)는 안 준다. 이름을 지어내지 않는다(규칙 3).
            say("화자명은 넣지 못했습니다 — 대본이 없으면 누가 말했는지 알 수 없습니다."
                " 영상을 보며 사람이 넣어야 합니다(--script로 대본을 주면 붙입니다).")

    revisions_out: list = []
    if translator is not None:
        from .translate import to_events, translate_events
        if keep_source:
            from .writers import write_srt
            write_srt(events, Path(keep_source))
            say(f"원어 자막을 남겼습니다: {keep_source}")
        target_lang = profile.get("language") or "ko"
        target_name = {"ko": "한국어", "en": "영어"}.get(target_lang, target_lang)
        say(f"{target_name}로 옮깁니다 — 자막 {len(events)}개")
        sources = {e.index: e.text for e in events}
        cues = translate_events(events, translator, glossary, progress=say,
                                target_lang=target_lang)
        for cue in cues:
            if cue.note:
                notes.append((cue.index, cue.note))
        events = to_events(cues, events)
        stats["translated"] = len(cues)

        if passes > 1:
            from .pipeline import stage_revise
            later = stage_revise(
                events, profile, translator=translator, source=sources,
                glossary=glossary, rounds=passes - 1,
                max_rounds=(max_passes - 1 if max_passes > passes else 0),
                settle_at=settle_at, cast=cast, target_lang=target_lang,
                progress=say)
            events = later.events
            revisions_out = later.extra["revisions"]
            stats["revision_rounds"] = later.extra["rounds"]
            stats["revision_stopped_because"] = later.extra["stopped_because"]

    before, origins = len(events), []
    events = resplit_all(events, profile, speech, origins)
    say(f"자막 {before}개를 의미 단위로 다시 나눠 {len(events)}개")

    # 번호가 다시 매겨졌다. 표시해 둔 자리를 새 번호로 옮긴다 — 안 하면 노트가
    # 엉뚱한 자막을 가리킨다.
    if notes:
        moved: dict[int, list[str]] = {}
        for new_index, old_index in enumerate(origins, 1):
            for old, note in notes:
                if old == old_index:
                    moved.setdefault(new_index, []).append(note)
        notes = [(i, " / ".join(v)) for i, v in sorted(moved.items())]

    # **인점·아웃점을 말소리에 맞춘다.** 작업자 기준: 인점은 목소리 시작 2~3프레임
    # 전, 아웃점은 끝난 뒤 6~9프레임. whisper가 찍은 경계는 이 여유를 모른다.
    #
    # 검사 경로에서는 이 조정을 자동으로 하지 않는다 — 사람이 잡은 타임코드를
    # 추정값으로 덮어쓰면 싱크가 통째로 어긋나기 때문이다. 여기서는 타임코드 자체가
    # 방금 기계가 만든 것이라 훼손할 작업물이 없다.
    from .timing import apply_spotting, suggest_spotting
    suggestions = suggest_spotting(events, speech, fps, detector=how)

    # **장면 전환도 스포팅의 일부다.** 전에는 `--check --fix-spotting`
    # 경로에서만 이 조정을 했고 `--generate` 자체는 몰랐다 — 만든 초안이
    # 애초부터 장면 전환을 하나도 안 본 채로 나왔다는 뜻이다. 넷플릭스 공식
    # "Timed Text Style Guide: Subtitle Timing Guidelines"(2026-08-28 확인,
    # "These rules are applicable to all timed text files produced for
    # Netflix" — SDH 전용이 아니라 번역 자막에도 적용된다): 인점이 장면
    # 전환 뒤 0.5초 안이면 전환 첫 프레임으로, 아웃점이 전환 앞 0.5초
    # 안이면 전환 2프레임 전으로 당긴다.
    if (profile.get("shot_change") or {}).get("applied"):
        from .media import detect_shot_changes
        from .timing import suggest_shot_snap
        shots = detect_shot_changes(video)
        say(f"장면 전환 {len(shots)}곳")
        suggestions += suggest_shot_snap(events, shots, fps)

    moved = apply_spotting(events, suggestions)
    if moved:
        say(f"인점·아웃점 {moved}곳을 말소리에 맞춤")
    stats["spotting_applied"] = moved

    result = converge(events, TimingLimits.from_profile(profile, fps=fps))
    say(f"스포팅 {len(result.changes)}곳 조정, 남은 문제 {len(result.unresolved)}건")
    stats.update(cues_out=len(result.events), timing_changes=len(result.changes),
                 timing_unresolved=len(result.unresolved))

    # 재분할로 번호가 바뀌었으면 원어도 새 번호로 옮긴다.
    moved_sources: dict[int, str] = {}
    if translator is not None:
        for new_index, old_index in enumerate(origins, 1):
            if old_index in sources:
                moved_sources[new_index] = sources[old_index]

    return Draft(result.events, notes, stats, moved_sources, revisions_out)


def _to_events(cues: list[AlignedCue], notes: list[tuple[int, str]]) -> list[Event]:
    """대조 결과를 자막으로. 봐야 할 자리는 번호를 적어 둔다.

    소리를 못 찾은 스크립트 줄은 **길이 0으로 남긴다**. 지우면 사람이 빠진 줄을
    영영 모르고, 아무 데나 시간을 주면 틀린 자막이 완성본처럼 보인다.
    """
    events: list[Event] = []
    for i, cue in enumerate(cues, 1):
        events.append(Event(i, cue.start_ms, cue.end_ms, cue.text))
        if cue.needs_review:
            notes.append((i, cue.note))
    return events


def notes_srt(draft: Draft) -> str:
    """봐야 할 자리를 자막 파일로. SE 번역 모드로 초안 옆에 띄우면 그 자리로 바로 간다."""
    from .writers import to_srt
    by_index = dict(draft.notes)
    return to_srt([Event(ev.index, ev.start_ms, ev.end_ms,
                         by_index.get(ev.index, "·"))
                   for ev in draft.events])
