"""비대사 소리(효과음)를 오디오 분류 모델로 짐작한다 — 대사 없는 구간에 무슨
소리가 나는지.

**1단계: 짐작만 한다. 보고용이다(규칙4).** whisper는 말소리만 받아 적는다 —
정답 SDH가 담는 `[groans]`·[♪ music playing]` 같은 순수 효과음 자막은 처음부터
파이프라인 밖이었다(2026-08-31, 영화B·영화A·드라마B
정답 대조에서 "빠뜨림"의 상당수가 이 종류였음을 실측 확인, `docs/BACKLOG.md`
§0-C — "이 오디오가 대사인지 아닌지 판별하는 기능이 없다"). 오디오 분류 모델
(AudioSet 527종 라벨, MIT/ast-finetuned-audioset)로 대사 없는 구간마다 "무슨
소리 계열인가"까지는 짐작할 수 있다.

**분위기·구체 동작은 오디오만으론 못 정한다.** `rules/lexicon/ko-sdh-effects.yaml`은
같은 "음악"도 "[따뜻한 음악]"·"[슬픈 음악]"·"[긴장되는 음악]"처럼 분위기별로
나뉘고, "[신발을 쓱 벗는다]"처럼 화면을 봐야 아는 구체 동작도 있다 — 이런 건
오디오 분류가 못 잡는다(같은 자료, "화면을 봐야 아는 구체적 내용은 오디오만으로
못 만든다"). `AUDIOSET_TO_CANDIDATE`는 그래서 **수식어 없는 가장 일반형만** 담는다
— 후보를 낼 뿐 사람이 문맥을 보고 다듬는다.

**2단계(`--generate --sfx`, 2026-08-31): `sound_events_to_draft_events()`·
`merge_sound_events()`를 추가했다.** `candidate`가 있는 것만 최종 자막에
얹는다 — 매핑 없는 라벨(`--sfx-scan`에만 나오는 것)은 여전히 지어내지
않는다. **얹은 자리마다 예외 없이 "확인 필요" 노트를 남긴다** — OCR의
저신뢰도만 표시하는 방식과 다르다(`merge_captions`의 `note_below`).
이유: OCR은 화면에 실제로 있는 글자를 읽는 것이라 신뢰도가 높으면 그대로
믿을 근거가 있지만, 오디오 분류는 "무슨 소리 계열인가"만 맞혀도 정확한
한국어 표현(분위기·구체 동작)은 항상 사람이 다듬어야 하는 초벌이다 —
확신도와 무관하게 전부 규칙4의 "추정"이다.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .media import _as_tool_path, _find
from .model import Event

MODEL_NAME = "MIT/ast-finetuned-audioset-10-10-0.4593"

_MODEL_CACHE: dict = {}


class SfxUnavailable(Exception):
    pass


def _load_model():
    """모델과 함께 numpy·torch·scipy도 여기서 불러온다.

    **2026-08-31, 코드 리뷰로 발견**: 예전엔 이 셋을 `detect_sound_events()`
    맨 위에서 아무 보호 없이 import했다 — 이 컴퓨터가 실제로 겪는 실패
    (torchcodec DLL 로드 실패, 모듈 독스트링 참고)는 `OSError`인데
    `except ImportError`로만 잡고 있어서 그대로 새어 나갔다. 필요한 것을
    전부 이 함수 하나로 모아 어떤 예외든 `SfxUnavailable`로 바꾼다.
    """
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"], _MODEL_CACHE["extractor"]
    try:
        import numpy  # noqa: F401
        import torch  # noqa: F401
        from scipy.io import wavfile  # noqa: F401
        from transformers import ASTForAudioClassification, AutoFeatureExtractor
    except Exception as exc:  # noqa: BLE001 - ImportError뿐 아니라 OSError(DLL)도 온다
        raise SfxUnavailable(
            f"오디오 분류에 필요한 패키지를 못 불러왔습니다({exc}). "
            "pip install transformers torch scipy") from exc
    try:
        extractor = AutoFeatureExtractor.from_pretrained(MODEL_NAME)
        model = ASTForAudioClassification.from_pretrained(MODEL_NAME)
        model.eval()
    except Exception as exc:  # noqa: BLE001 - 모델 다운로드 실패 경로가 다양하다
        raise SfxUnavailable(f"오디오 분류 모델을 불러오지 못했습니다({exc})") from exc
    _MODEL_CACHE["model"] = model
    _MODEL_CACHE["extractor"] = extractor
    return model, extractor


# AudioSet 라벨(영어, 원문 그대로) -> 한국어 SDH 후보 문구(수식어 없는 일반형).
# `rules/lexicon/ko-sdh-effects.yaml`에서 가장 넓게 쓰이는 표현만 골랐다.
# **확신 없는 라벨은 여기 안 넣는다** — 매핑이 없으면 원 라벨만 보고하고
# 후보는 비워 둔다(지어내지 않는다, 규칙3).
AUDIOSET_TO_CANDIDATE = {
    "Music": "[음악이 흐른다]",
    "Musical instrument": "[악기 연주가 들려온다]",
    "Laughter": "[웃음]",
    "Giggle": "[웃음]",
    "Chuckle, chortle": "[웃음]",
    "Applause": "[힘찬 박수]",
    "Cheering": "[환호한다]",
    "Crying, sobbing": "[울음]",
    "Baby cry, infant cry": "[아기 울음 효과음]",
    "Cough": "[기침]",
    "Knock": "[노크 소리가 들린다]",
    "Door": "[문이 삐걱거린다]",
    "Doorbell": "[초인종이 울린다]",
    "Telephone bell ringing": "[휴대 전화 벨 소리]",
    "Ringtone": "[휴대 전화 벨 소리]",
    "Vehicle": "[자동차 엔진음]",
    "Car": "[자동차 엔진음]",
    "Siren": "[사이렌이 울린다]",
    "Gunshot, gunfire": "[총성]",
    "Glass": "[유리가 와장창 깨진다]",
    "Shatter": "[유리가 와장창 깨진다]",
    "Zipper (clothing)": "[지퍼를 직 연다]",
    "Keys jangling": "[열쇠를 잘그랑거린다]",
    "Typing": "[키보드를 탁탁 친다]",
    "Computer keyboard": "[키보드를 탁탁 친다]",
    "Walk, footsteps": "[다급한 발소리]",
    "Dog": "[개 짖는 소리]",
    "Bark": "[개 짖는 소리]",
    "Bird vocalization, bird call, bird song": "[새 지저귐]",
    "Thunder": "[천둥이 우르릉 울린다]",
    "Wind": "[바람이 휭 분다]",
    "Water": "[물이 쏴 흘러나온다]",
    "Stream": "[물이 쏴 흘러나온다]",
}


# checker/checks.py의 music_marker_style(DP12류)과 같은 낱말 집합 — 대괄호
# 안 텍스트가 음악 관련인지 이 낱말로 가린다.
_MUSIC_KEYWORDS = ("음악", "곡", "연주", "노래")


def _apply_music_marker(text: str, note_inside_bracket: bool | None) -> str:
    """음악 관련 대괄호 문구에 플랫폼 규칙(DP12류)대로 ♪를 넣거나 뺀다.

    2026-08-31, 드라마B E01로 `--generate --sfx` 실제 통합 테스트 중 발견:
    디즈니 프로파일은 `[♪ 음악이 흐른다]`를 원하는데 고정 문구
    `[음악이 흐른다]`를 그대로 얹어 DP12 위반 126건을 만들었다. 검사가
    이 규칙을 자동 교정하지 않아(`checker/fixes.py`에 없음) 사람이 매번
    손으로 고쳐야 했다 — 생성 시점에 플랫폼을 이미 아니까 여기서 맞춘다.
    `note_inside_bracket`이 `None`이면(프로파일에 규정 없음) 손대지 않는다.
    """
    if note_inside_bracket is None or not (text.startswith("[") and text.endswith("]")):
        return text
    inner = text[1:-1]
    if not any(k in inner for k in _MUSIC_KEYWORDS):
        return text
    has_note = "♪" in inner
    if note_inside_bracket and not has_note:
        return f"[♪ {inner}]"
    if not note_inside_bracket and has_note:
        return f"[{inner.replace('♪', '').strip()}]"
    return text


@dataclass
class SoundEvent:
    start_ms: int
    end_ms: int
    label: str                 # AudioSet 원 라벨(영어)
    confidence: float
    candidate: str | None      # 매핑된 한국어 후보, 없으면 None(지어내지 않는다)


def speech_gaps(speech: list[tuple[int, int]], duration_ms: int,
               min_gap_ms: int = 1000) -> list[tuple[int, int]]:
    """말소리 구간 사이 빈 곳(대사 없는 자리)만 돌려준다. **순수 함수.**

    대사 위에 깔린 배경음(예: 대화 중 흐르는 음악)은 여기서 안 다룬다 — 그 자리는
    전사와 겹쳐서 화면까지 같이 봐야 판단할 수 있다.
    """
    gaps = []
    cursor = 0
    for s, e in sorted(speech):
        if s - cursor >= min_gap_ms:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if duration_ms - cursor >= min_gap_ms:
        gaps.append((cursor, duration_ms))
    return gaps


# 최종 자막 하나의 상한. 정확한 값은 플랫폼마다 다르지만(디즈니 7000ms 등)
# 여기는 생성 파이프라인 진입 전이라 프로파일을 모른다 — 넉넉히 잡아 둔다.
# **`converge()`가 나중에 다시 봐 주지 않는다**(2026-08-31, 코드 리뷰로
# 발견 — sfx 병합은 `generate()`가 이미 끝난 뒤 cli.py에서 따로 돈다).
# 상한이 없으면 같은 라벨이 오래 이어질 때(정적 화면 음악 등) 자막 하나가
# 몇 분씩 갈 수 있다.
_MAX_EVENT_MS = 8000
# AST 모델의 위치 임베딩이 1024프레임(16kHz 기준 10.24초)까지만 있다 — 더 긴
# 오디오를 통째로 넣으면 추출기가 자르거나 자체 처리하는데, 어느 쪽이든 top-1
# 라벨이 구간 **첫 10초만** 대표한다(2026-08-31, 코드 리뷰로 발견 — 60초짜리
# 음악 구간 하나가 통째로 SoundEvent 하나가 되어 그 안 내용 변화를 놓쳤다).
# 그래서 긴 구간은 이 창 단위로 나눠 각각 새로 분류한다. **`_MAX_EVENT_MS`
# 이하로 잡는다** — 창 하나가 곧 자막 하나가 될 수 있으니(합쳐질 이웃이
# 없으면), 창 자체가 상한을 넘으면 그 상한 자체가 무의미해진다.
_WINDOW_MS = _MAX_EVENT_MS // 2


def _windows(start_ms: int, end_ms: int, size_ms: int) -> list[tuple[int, int]]:
    """`[start_ms, end_ms)`를 `size_ms` 이하 창으로 나눈다. **순수 함수.**"""
    out = []
    cursor = start_ms
    while cursor < end_ms:
        out.append((cursor, min(cursor + size_ms, end_ms)))
        cursor += size_ms
    return out


def detect_sound_events(video: Path, speech: list[tuple[int, int]], duration_ms: int,
                        min_gap_ms: int = 1000, min_confidence: float = 0.3,
                        progress=None) -> list[SoundEvent]:
    """대사 없는 구간마다 오디오 분류 모델로 무슨 소리인지 짐작한다.

    **보고용이다.** 자막 Event로 만들거나 자동 반영하지 않는다 — 모듈 독스트링
    참고. 각 구간을 `_WINDOW_MS` 이하로 나눠 창마다 분류하고(모델 입력 길이
    한계, 위 상수 설명 참고), 같은 라벨이 이어지는 창은 하나로 합치되
    `_MAX_EVENT_MS`를 넘기면 거기서 자른다. 창마다 top-1 라벨만 본다 —
    여러 후보를 늘어놓기 시작하면 사람이 결국 다 들어봐야 해서 이득이 없다.
    """
    say = progress or (lambda _m: None)
    model, extractor = _load_model()
    import numpy as np
    import torch
    from scipy.io import wavfile

    gaps = speech_gaps(speech, duration_ms, min_gap_ms)
    windows = [w for gap in gaps for w in _windows(gap[0], gap[1], _WINDOW_MS)]
    say(f"대사 없는 구간 {len(gaps)}곳({len(windows)}개 창)에서 소리를 짐작합니다")

    # (start_ms, end_ms, label, score) — None 라벨은 확신 미달로 버린 창.
    classified: list[tuple[int, int, str | None, float]] = []
    failures = 0
    last_ffmpeg_error = ""
    with tempfile.TemporaryDirectory(prefix="sfx_") as tmp:
        clip_path = Path(tmp) / "clip.wav"
        for start_ms, end_ms in windows:
            result = subprocess.run(
                [_find("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", str(start_ms / 1000), "-i", _as_tool_path(video),
                 "-t", str((end_ms - start_ms) / 1000),
                 "-ac", "1", "-ar", "16000", "-vn", _as_tool_path(clip_path)],
                capture_output=True)
            if result.returncode != 0 or not clip_path.is_file():
                failures += 1
                last_ffmpeg_error = (result.stderr or b"").decode("utf-8", errors="replace").strip()
                continue
            sr, data = wavfile.read(clip_path)
            if data.size == 0:
                continue
            if np.issubdtype(data.dtype, np.integer):
                data = data.astype(np.float32) / 32768.0
            else:
                data = data.astype(np.float32)

            inputs = extractor(data, sampling_rate=sr, return_tensors="pt")
            with torch.no_grad():
                logits = model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)[0]
            top_score, top_idx = torch.max(probs, dim=0)
            score = top_score.item()
            label = model.config.id2label[top_idx.item()] if score >= min_confidence else None
            classified.append((start_ms, end_ms, label, score))

    # **모든(또는 거의 모든) 창이 ffmpeg 실패면 "소리 없음"이 아니라 오류다**
    # (2026-08-31, 코드 리뷰로 발견 — 전엔 조용히 넘어가 "0곳 찾음"으로 보여서
    # 실패와 무음을 구분 못 했다).
    if windows and failures == len(windows):
        raise SfxUnavailable(f"오디오 클립을 하나도 못 뽑았습니다({last_ffmpeg_error})")
    if failures:
        say(f"오디오 클립 추출 실패 {failures}/{len(windows)}곳(무시하고 계속) — {last_ffmpeg_error}")

    # 이어지는 같은 라벨 창을 하나로 합치되 _MAX_EVENT_MS에서 자른다.
    events: list[SoundEvent] = []
    run_start = run_end = None
    run_label = None
    run_scores: list[float] = []

    def _flush():
        if run_label is not None:
            events.append(SoundEvent(run_start, run_end, run_label,
                                     max(run_scores), AUDIOSET_TO_CANDIDATE.get(run_label)))

    for start_ms, end_ms, label, score in classified:
        same_run = (label is not None and label == run_label
                   and start_ms == run_end and end_ms - run_start <= _MAX_EVENT_MS)
        if same_run:
            run_end = end_ms
            run_scores.append(score)
            continue
        _flush()
        run_start, run_end, run_label, run_scores = start_ms, end_ms, label, [score]
    _flush()

    say(f"소리 후보 {len(events)}곳 찾음")
    return events


def sound_events_to_draft_events(events: list[SoundEvent], start_index: int = 1,
                                 music_note_in_bracket: bool | None = None) -> list[Event]:
    """`candidate`가 있는 `SoundEvent`만 `kind="sfx"` `Event`로 바꾼다.

    매핑 없는 라벨(`candidate is None`)은 뺀다 — 원 라벨만으로 한국어 자막을
    지어내지 않는다(규칙3). 번호는 임시값이다(`merge_sound_events()`가 최종
    번호를 다시 매긴다) — `start_index`는 대사 이벤트 번호와 안 겹치게
    호출하는 쪽이 정한다.

    `music_note_in_bracket`은 `profile.get("music", {}).get("note_inside_bracket")`을
    그대로 넘긴다 — 음악 관련 후보에 플랫폼 규칙대로 ♪를 넣거나 뺀다
    (`_apply_music_marker()` 참고, 안 주면 손대지 않는다).
    """
    mapped = [e for e in events if e.candidate]
    return [Event(start_index + i, e.start_ms, e.end_ms,
                  _apply_music_marker(e.candidate, music_note_in_bracket), kind="sfx")
           for i, e in enumerate(mapped)]


_MIN_SFX_DURATION_MS = 500


def merge_sound_events(dialogue_events: list[Event], dialogue_notes: list[tuple[int, str]],
                       sfx_events: list[Event], dialogue_sources: dict[int, str] | None = None,
                       ) -> tuple[list[Event], list[tuple[int, str]], dict[int, str]]:
    """소리 후보(`Event`, `kind="sfx"`)를 대사 이벤트에 합친다. **순수 함수처럼
    쓴다** — 다만 겹침을 풀며 `Event.start_ms/end_ms/index`를 제자리에서
    고친다(입력 리스트를 재사용하지 않는다).

    `merge_captions()`(`ocr.py`)와 구조는 같지만 노트 규칙이 다르다 — 여기서는
    **얹은 자리마다 예외 없이** "확인 필요"를 남긴다(모듈 독스트링 참고,
    OCR처럼 신뢰도로 가르지 않는다).

    **이웃 대사와 겹치면 밀어내고, 너무 짧아지면 버린다**(2026-08-31, 코드
    리뷰로 발견) — 스포팅(`timing.py`의 `LEADS`)이 대사 아웃점을 말소리
    구간 끝보다 늦게 늘릴 수 있어서, 그 자리에 얹은 소리 후보가 대사와
    겹칠 수 있다. 겹침을 없앤 뒤 `_MIN_SFX_DURATION_MS`보다 짧아지면 그
    소리 후보는 통째로 버린다 — 애매한 후보 하나보다 자막이 안 겹치는 게
    먼저다.

    **인점은 `kept[-1]`(실제로 살아남은 직전 이웃)을 본다 — `combined[i-1]`이
    아니다**(2026-08-31, 드라마B E01 실전 검증에서 재발견). 방금 버려진 소리
    후보를 `combined[i-1]`로 참조하면, 그 버려진 후보의(더 이른) 원래
    끝점을 기준으로 다음 후보를 미는 바람에 정작 그 앞의 진짜 대사와는
    여전히 겹친 채로 남는다 — 실측: 대사 하나 사이에 VAD가 짧은 침묵을
    두 번 잘못 감지해 소리 후보가 3개 연속으로 나왔는데, 가운데 것이
    버려지면서 세 번째 것이 `combined[i-1]`(버려진 두 번째 것)의 이른
    끝점만 보고 진짜 이웃(첫 번째 대사)과 겹친 채 통과했다. 아웃점은
    `combined[i+1]`(원래 순서의 다음 항목)을 그대로 봐도 안전하다 — 그
    항목이 나중에 버려지거나 밀리더라도 원래 시작점을 상한으로 쓰는 건
    항상 보수적인 선택이라 겹침을 만들지 않는다.

    `dialogue_sources`(`Draft.sources`)를 주면 새 번호로 옮겨 함께
    돌려준다 — 안 옮기면 번역 원어 표시가 밀린 번호를 가리키게 된다.
    """
    dialogue_index_by_id = {id(e): e.index for e in dialogue_events}
    combined = sorted(dialogue_events + sfx_events, key=lambda e: e.start_ms)

    kept: list[Event] = []
    for i, e in enumerate(combined):
        if e.kind != "sfx":
            kept.append(e)
            continue
        start_ms, end_ms = e.start_ms, e.end_ms
        if kept:
            start_ms = max(start_ms, kept[-1].end_ms)
        if i + 1 < len(combined):
            end_ms = min(end_ms, combined[i + 1].start_ms)
        if end_ms - start_ms < _MIN_SFX_DURATION_MS:
            continue
        e.start_ms, e.end_ms = start_ms, end_ms
        kept.append(e)
    combined = kept

    remap: dict[int, int] = {}
    sfx_notes: list[tuple[int, str]] = []
    for new_i, e in enumerate(combined, 1):
        if e.kind == "sfx":
            sfx_notes.append((new_i, "오디오 분류 추정 — 화면 보고 확인 필요"))
        else:
            remap[dialogue_index_by_id[id(e)]] = new_i
        e.index = new_i

    merged_notes = [(remap.get(i, i), msg) for i, msg in dialogue_notes] + sfx_notes
    merged_sources = {remap.get(i, i): text for i, text in (dialogue_sources or {}).items()}
    return combined, merged_notes, merged_sources
