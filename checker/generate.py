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

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .align import AlignedCue, Segment, align, summary
from .media import find_speech, probe
from .model import Event
from .text import chars_per_second
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


# whisper가 침묵·저음량 구간에서 재현하는 것으로 널리 보고된 문구들
# (whisper.cpp·openai-whisper 커뮤니티, 유튜브 자동자막 학습 데이터의 흔적으로
# 추정). 대사가 우연히 이 문구와 겹칠 확률은 무시할 만하다 — 텍스트 자체로
# 판정 가능하니 규칙4의 "파일 안에서 알 수 있는 것"에 해당해 자동으로 지운다
# (VAD 안 겹침처럼 오디오에서 추정하는 판단과는 다르다). 대소문자·문장부호는
# 안 가린다.
KNOWN_HALLUCINATION_PHRASES = (
    "transcribed by", "transcript by", "translated by", "subtitled by",
    "subtitles by", "captions by", "closed captioning by",
    "amara.org", "opensubtitles",
    "thank you for watching", "thanks for watching",
    "please subscribe", "like and subscribe", "subscribe to my channel",
)


def _is_known_hallucination(text: str) -> bool:
    """`KNOWN_HALLUCINATION_PHRASES`에 걸리거나, 글자다운 글자가 하나도 없는
    (대시·말줄임표 등 whisper의 "잘 안 들림" 자리표시자만 있는) 조각이면 참.

    후자 실측(2026-08-31, 영화A 오프닝): "—"만 있는 조각이 수십 개
    떴다 — 실제 대사라면 문자(letter)가 하나도 없을 수 없다.
    """
    stripped = text.strip()
    if not stripped:
        return True
    lower = stripped.lower()
    if any(phrase in lower for phrase in KNOWN_HALLUCINATION_PHRASES):
        return True
    return not any(ch.isalnum() for ch in stripped)


def has_vad_support(start_ms: int, end_ms: int, speech: list[tuple[int, int]],
                    speech_end: int, undetected_after: bool) -> bool:
    """이 구간이 VAD가 잡은 말소리 구간과 겹치는지. `generate()`가 자막마다
    묻는다 — 겹치지 않으면 지우지 않고 "확인 필요"로만 표시한다(2026-08-31,
    영화B 정답 대조에서 배경음악에 묻힌 진짜 대사를 VAD가 놓치는
    사례를 확인한 뒤 정정 — 예전엔 여기서 조용히 지웠다).

    `undetected_after`가 참이고 `start_ms`가 `speech_end`(VAD가 마지막으로
    본 자리) 이후면 무조건 겹치는 것으로 본다 — VAD 검출 자체가 못 미친
    구간이라 "침묵"과 "검출 실패"를 구분 못 하기 때문이다(예능A 15회
    사고 참고, 위 `generate()`의 관련 주석).
    """
    if not speech:
        return True   # VAD 자체가 없으면(음량 방식 등) 이 판단을 안 한다
    if undetected_after and start_ms >= speech_end:
        return True
    return any(s < end_ms and start_ms < e for s, e in speech)


def generate(video: Path, profile: dict, script: Path | None = None,
             language: str = "auto", model: str | None = None,
             fps: float | None = None, use_gpu: bool = True,
             keep_transcript: Path | None = None, translator=None,
             glossary=None, keep_source: Path | None = None,
             speech_method: str = "auto", diarize: bool = False,
             passes: int = 1, max_passes: int = 0, settle_at: int = 0,
             cast: dict[str, str] | None = None,
             transcript_cache: Path | None = None,
             context_checker=None,
             foreign_dialogue_translator=None,
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

    `context_checker`를 주면(번역기와 같은 `ask(system, prompt)` 인터페이스)
    번역 전에 전사 원문이 앞뒤 맥락과 맞는지 확인해 알린다(`context_check.py`).
    `translator`와 별개다 — 번역을 안 하는 SDH 작업에도 켤 수 있다.

    `foreign_dialogue_translator`를 주면(같은 `ask` 인터페이스) 원어(대개 한국어)
    사이에 섞인 외국어 대사를 한국어로 옮기고 언어 표시를 붙인다
    (`foreign_dialogue.py` — 2026-08-30, 드라마B E01을 정답과 대조해
    발견: 정답은 일본어 대사를 한국어로 옮기는데 우리는 그대로 전사만 했다).
    이것도 초안이다 — 옮긴 자리마다 notes에 남는다.
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

    # **whisper 전사가 같은 영상에서도 매번 다르게 나온다** — faster-whisper로
    # 실측(2026-08-30, 드라마B E01, 같은 명령 5번): 세그먼트
    # 290·705·709·747·756개. 4번은 700대로 몰렸는데 1번(290)만 확 튀었다 —
    # 우리 VAD가 찾은 말소리 구간(660개, 이건 결정적이다) **보다도 적은** 세그먼트가
    # 나온 게 그 한 번뿐이다. 정상 실행은 항상 말소리 구간보다 세그먼트가
    # 많았다(구간 하나가 세그먼트 여러 개로 쪼개지는 게 보통이라). 그래서
    # "세그먼트가 말소리 구간보다 뚜렷이 적다"를 실패 신호로 보고 **한 번만**
    # 다시 돌린다 — 표본이 5번뿐이라 이 판단 자체가 아직 가설이다. 계속
    # 쌓이는 실측은 `docs/whisper_retry_log.jsonl`에 남는다(사람이 나중에
    # 유의미한지 판단할 근거).
    SUSPECT_RATIO = 0.9
    retried = False
    if transcript_cache is None and speech and len(segments) < len(speech) * SUSPECT_RATIO:
        say(f"전사 세그먼트({len(segments)}개)가 말소리 구간({len(speech)}개)보다 "
            "뚜렷이 적습니다 — 실패로 의심해 한 번 더 전사합니다")
        retry_segments = transcribe(video, language=language, model=model,
                                    use_gpu=use_gpu, progress=say, keep=keep_transcript,
                                    cache=None)
        retried = True
        if len(retry_segments) > len(segments):
            segments = retry_segments
        else:
            say("다시 돌려도 나아지지 않았습니다 — 이번 결과를 그대로 씁니다."
                " 사람이 직접 확인하는 것을 권합니다.")

    from .paths import user_data
    try:
        log_path = user_data() / "whisper_retry_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "date": datetime.now().isoformat(timespec="seconds"),
                "video": video.name,
                "duration_ms": media.duration_ms,
                "speech_spans": len(speech),
                "segments_used": len(segments),
                "suspected_failure": retried,
            }, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 로그는 참고용이다 — 못 남겨도 생성 자체를 막지 않는다

    if not segments:
        return Draft([], [], {"transcript": 0})

    # **whisper의 "유명한" 침묵 환각 문구는 지운다.** VAD 안 겹침 필터(아래)는
    # "배경음에 묻힌 진짜 대사"와 "침묵에서 지어낸 것"을 못 가려서 이제
    # 지우지 않고 표시만 한다(2026-08-31 정정, 바로 아래 참고) — 그런데
    # 이 문구들은 다르다. 텍스트 자체가 정답이라 **추정이 아니라 사실**이다
    # (규칙 4: 파일 안에서 알 수 있는 것은 자동으로 고친다). whisper가
    # 유튜브 자동자막으로 학습되며 침묵·저음량 구간에서 그 학습 자료에 있던
    # 크레딧 문구를 그대로 재현하는 건 whisper.cpp·openai-whisper 커뮤니티에
    # 널리 보고된 현상이다(2026-08-31, 영화A 오프닝에서 실측:
    # "Transcribed by ESO, translated by —"가 여러 번, "—"만 있는 조각이
    # 수십 개). 실제 대사가 이 문구와 우연히 겹칠 확률은 무시할 만하다.
    before_known = len(segments)
    segments = [s for s in segments if not _is_known_hallucination(s.text)]
    if len(segments) != before_known:
        say(f"whisper의 유명한 침묵 환각 문구 {before_known - len(segments)}개를 지웠습니다"
            " — 실제 대사가 아니라고 텍스트 자체로 확인됩니다")
    if not segments:
        return Draft([], [], {"transcript": 0})

    # **말소리 구간과 전혀 안 겹치는 조각은 더 이상 여기서 지우지 않는다
    # (2026-08-31 정정).** 원래 이 필터는 whisper가 완전한 침묵에서도 자신
    # 있게 글자를 지어내는 문제를 잡으려고 만들었다(2026-08-26, 영화D·영화F
    # and Monsters 두 영화의 오프닝 로고 구간에서 밀리초까지 같은 타임스탬프에
    # "네! 네! 네!"·"헤이 헤이 헤이" 같은 반복이 나온 것으로 확인). 그런데
    # "실제 말소리가 조금이라도 있으면 VAD가 잡는다"는 전제가 틀렸다 —
    # 영화B 정답 대조(2026-08-31)에서 VAD(음성 모델)가 배경음악이
    # 깔린 구간(예: 125~190초, 378~396초)에서 실제 대사("Hello!"·"Where is
    # the fuel?"·"Wait." 등, whisper는 정확히 받아 적었다)를 통째로 못 잡는
    # 사례를 직접 확인했다 — 65초·18초 구간이 대사가 있었는데도 통째로
    # 사라졌다. 게다가 이 자리 원래 주석부터가 "지우지 않고 세어서 알린다"고
    # 적어 놓고 실제로는 `segments = kept`로 지우고 있었다 — 규칙 4(추정으로
    # 자동 교정하지 않는다)를 코드가 어기고 있었다.
    #
    # 그래서 여기서는 **VAD 커버리지만 계산해 두고, 최종 자막까지 살아남는지는
    # 아래 환각 의심 검사 단계로 넘긴다** — 밀도(CPS)·신뢰도와 함께 봐야
    # "짧지만 진짜 한 말"과 "침묵에서 지어낸 반복"을 더 잘 가른다(주석
    # 그대로: 지우지 않고 표시만 한다).
    #
    # **VAD의 오디오 읽기 자체가 도중에 멎을 수 있다.** 컨테이너 손상 등으로
    # ffmpeg이 오디오를 끝까지 못 읽으면 `speech`가 영상 길이보다 훨씬 짧게
    # 끝난다 — 그 뒤는 "침묵"이 아니라 "검출을 못 한 구간"이다. 실측(2026-08-27,
    # 예능A 15회): VAD는 3113초에서 멎었는데 whisper 전사는 3478초까지
    # 멀쩡했다. 이 구분 없이 필터를 걸었더니 **실제 대사가 있는 마지막 6분이
    # 통째로 삭제되는 사고**가 났다 — 아래 검사에서도 이 구간은 판단을 보류한다.
    speech_end = max((e for _, e in speech), default=0)
    coverage_gap = media.duration_ms - speech_end
    # 30초는 여유값이다. 진짜 무음 엔딩(크레딧 등)은 이보다 짧은 게 보통이고,
    # 몇 분 단위로 벌어지면 검출 자체가 멎었다고 본다.
    undetected_after = bool(speech) and coverage_gap > 30_000

    if undetected_after:
        say(f"말소리 검출이 영상 끝보다 {coverage_gap / 1000:.0f}초 일찍 "
            "멎었습니다 — 그 뒤는 침묵으로 보지 않고 그대로 둡니다"
            "(검출 자체가 못 미쳤을 수 있습니다)")

    def _has_vad_support(start_ms: int, end_ms: int) -> bool:
        return has_vad_support(start_ms, end_ms, speech, speech_end, undetected_after)

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
        from .regroup import (limits_from_profile, merge_cues, compress_reaction_runs,
                              collapse_internal_duplicates)
        raw = [Event(i, s.start_ms, s.end_ms, s.text) for i, s in enumerate(segments, 1)]
        max_ms, max_gap = limits_from_profile(profile)

        # **자막 하나 안에 같은 말이 겹쳐 들어온 자리부터 정리한다.** 이건
        # compress_reaction_runs(자막 여러 개가 반복될 때)보다 먼저다 — 원인이
        # 다르다(regroup.py의 collapse_internal_duplicates 문서 참고).
        raw = collapse_internal_duplicates(raw)

        # **짧은 반응이 연달아 겹치는 자리를 먼저 압축한다.** `merge_cues`보다
        # 먼저 돈다 — 순서가 반대면 `merge_cues`가 짧은 반응 몇 개를 이미 거칠게
        # 이어붙여(공백으로 텍스트만 연결) 놓은 뒤라, 압축 단계가 그 지저분한
        # 텍스트를 넘겨받아 제대로 못 거른다(2026-08-30, 예능A 16회 실측 —
        # "아…" 5개가 4개→2개까지만 줄고 "아... -아..." 같은 지저분한 텍스트로
        # 남았다. 순서를 바꾸니 원시 조각 단계에서 깔끔하게 하나로 걸러졌다).
        # merge_cues는 "한 호흡"을 합치고, 이 단계는 서로 떨어진 짧은 반응
        # 여러 개(감탄사 반복 등)를 압축한다 — 정답 SDH는 이런 자리를 화면
        # 하나로 압축한다. 텍스트는 지어내지 않고 실제로 들은 것 중 최대 2개
        # 까지만 남긴다(규칙 4).
        before = len(raw)
        raw = compress_reaction_runs(raw)
        if len(raw) != before:
            say(f"짧은 반응 반복 자리를 압축해 전사 조각 {before}개를 {len(raw)}개로 줄였습니다")

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

    # **섞인 외국어 대사를 한국어로 옮긴다.** 문맥 확인·메인 번역보다 먼저다 —
    # 뒤 단계는 이 자리가 이미 원어(대개 한국어)라고 가정한다. 옮기지 않으면
    # 외국어 그대로 다음 단계로 넘어가 문맥 확인이 헷갈리고, 재분할(resplit)의
    # 글자 수 계산도 엉뚱한 언어 기준으로 된다.
    if foreign_dialogue_translator is not None:
        from .foreign_dialogue import translate_foreign_dialogue
        events, foreign_notes = translate_foreign_dialogue(
            events, foreign_dialogue_translator, progress=say)
        notes.extend(foreign_notes)

    # **원어 전사가 앞뒤 맥락과 맞는지 번역 전에 확인한다.** whisper는 비슷하게
    # 들리는 다른 말로 잘못 듣고도 문법이 멀쩡한 문장을 만든다(`context_check.py`
    # 첫머리 참고) — 번역해 버리면 원문의 이상함이 자연스러운 한국어 뒤에 숨는다.
    # 이것도 추정이라 고치지 않고 알리기만 한다(규칙 4).
    if context_checker is not None:
        from .context_check import flag_context_mismatches
        mismatches = flag_context_mismatches(events, context_checker, progress=say)
        if mismatches:
            say(f"문맥과 안 맞는 전사 {len(mismatches)}곳 — 잘못 들었을 수 있습니다."
                " 영상에서 직접 들어보고 확인하세요:")
            notes.extend((i, f"문맥 불일치 의심: {reason}") for i, reason in mismatches)

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

    # **환각 의심 자막을 알린다(자동으로 고치지 않는다, 규칙 4).** 2026-08-30,
    # 드라마B E01 잡음 섞인 뉴스 몽타주 구간(1970년대 항공기 납치 사건
    # 자료화면)에서 whisper가 "- - - - -"·"일본어의 351 한ada 덮바러" 같은 뜻
    # 없는 글자를 뱉었다.
    #
    # **이 검사는 통계(신뢰도·글자 밀도)만 본다 — 뜻은 안 본다.** "저희들은
    # 경산 시기세 동네, 각군派단"처럼 문법이 안 맞는데 글자 밀도는 정상인
    # 환각은 여기서 못 잡는다(2026-08-30 확인). **그건 `--check-context`
    # (`context_check.py`)의 몫이다** — 로컬 LLM으로 앞뒤 문맥이 맞는지 보는
    # 별도 검사라 뜻이 안 통하는 자리를 잡는다(E01 실측: 27곳, 이 검사와
    # 겹치지 않는 자리가 대부분). 잡음이 많은 자료(뉴스 몽타주·아카이브
    # 영상)는 **이 통계 검사만으로 충분하다고 보지 않는다** — `--check-context`를
    # 같이 켠다.
    #
    # **faster-whisper가 있으면 신뢰도(`avg_logprob`)를 같이 본다** — 같은 날
    # 직접 재 보니 깨끗한 대사는 -0.17, 이 잡음 구간은 -0.61로 뚜렷이 갈렸다.
    # 겹치는 원시 조각 중 가장 낮은(가장 불확실한) 값을 그 자막의 신뢰도로 본다.
    #
    # **신뢰도만으로는 안 된다.** `--whisper-lang ko`로 언어를 강제하면, 정확히
    # 옮긴 외국어 대사(예: "Japan Airways 351 clear for take-off" — 관제탑
    # 교신, 실제로 맞게 받아 적었다)도 모델이 "기대와 다른 언어"라 신뢰도가
    # 낮게 나온다(2026-08-30 실측, E01 재생성에서 145곳 중 다수가 이런 정상
    # 외국어 문장이었다). 그래서 **신뢰도 낮음 + 글자 밀도 낮음(3 CPS 미만)이
    # 같이 있을 때만** 잡는다 — 진짜 환각(예: "일본어의 351 한ada 덮바러")은
    # 시간 대비 글자가 적어서 CPS도 같이 낮지만, 정확히 옮긴 외국어 문장은
    # 글자가 정상적으로 촘촘해서 CPS가 낮지 않다(위 관제탑 예문은 275ms에
    # 134.5 CPS — 오히려 아주 높다). 신뢰도가 없으면(ffmpeg 내장 whisper
    # 필터 — srt·json 둘 다 이 값을 안 준다) "최대 표시 시간을 꽉 채웠는지"로
    # 대신한다. 어느 쪽이든 놓치는 것과 잘못 잡는 것이 있을 수 있다 — 그래서
    # 지우거나 고치지 않고 **알리기만** 한다.
    CONFIDENCE_THRESHOLD = -0.4
    SPARSE_CPS = 3.0

    def _worst_confidence(ev) -> float | None:
        values = [s.confidence for s in segments
                 if s.confidence is not None
                 and s.start_ms < ev.end_ms and ev.start_ms < s.end_ms]
        return min(values) if values else None

    dur_max = (profile.get("limits") or {}).get("duration_ms", {}).get("max")
    weights = (profile.get("limits") or {}).get("char_weights")
    has_confidence = any(s.confidence is not None for s in segments)
    suspects = []
    for ev in result.events:
        sparse = chars_per_second(ev.text, ev.duration_ms, weights) < SPARSE_CPS
        if has_confidence:
            conf = _worst_confidence(ev)
            if conf is not None and conf < CONFIDENCE_THRESHOLD and sparse:
                suspects.append(ev)
        elif dur_max and ev.duration_ms >= dur_max and sparse:
            suspects.append(ev)
    if suspects:
        basis = "신뢰도·글자 밀도 둘 다 낮음" if has_confidence else "시간을 꽉 채웠는데 글자가 적음"
        say(f"환각 의심 자막 {len(suspects)}곳({basis}) — 영상에서 직접 들어보고 확인하세요:")
        for ev in suspects[:20]:
            ts = ev.start_ms // 1000
            say(f"    #{ev.index} {ts // 60}:{ts % 60:02d}  {ev.text[:40]!r}")
        if len(suspects) > 20:
            say(f"    ...외 {len(suspects) - 20}곳 더")

    # **말소리 구간(VAD)과 전혀 안 겹치는 자막도 따로 알린다(2026-08-31,
    # 위쪽 `_has_vad_support` 정정과 짝).** 위 환각 의심 검사와 근거가 다르다
    # — 저건 통계(밀도·신뢰도)만 보고, 이건 VAD가 이 시간대에 소리 자체를
    # 아예 못 찾았는지를 본다. 원인이 둘일 수 있다: 배경음악·잡음에 묻힌
    # 진짜 대사를 VAD가 놓쳤거나(영화B 실측 — VAD가 못 잡은 65초 구간에
    # whisper는 "Hello!"·"It's magic." 등 실제 대사를 정확히 받아 적었다),
    # 또는 완전한 침묵에서 whisper가 지어낸 것(영화D·영화F 사례)이다.
    # 둘을 여기서 가리지 못하니 **지우지 않고 표시만** 한다 — 지우면 전자가
    # 손해, 안 지우면 후자가 사람 손이 한 번 더 간다. 둘 중 되돌릴 수 없는
    # 쪽(실제 대사 삭제)을 피한다.
    if speech:
        no_vad = [ev for ev in result.events
                 if not _has_vad_support(ev.start_ms, ev.end_ms)]
        if no_vad:
            say(f"말소리 구간(VAD)과 안 겹치는 자막 {len(no_vad)}곳 — 배경음에 묻힌 "
                "진짜 대사이거나 침묵에서 지어낸 것, 둘 다일 수 있습니다. "
                "영상에서 직접 들어보고 확인하세요:")
            for ev in no_vad[:20]:
                ts = ev.start_ms // 1000
                say(f"    #{ev.index} {ts // 60}:{ts % 60:02d}  {ev.text[:40]!r}")
            if len(no_vad) > 20:
                say(f"    ...외 {len(no_vad) - 20}곳 더")

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
