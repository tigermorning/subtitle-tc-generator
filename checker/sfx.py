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
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"], _MODEL_CACHE["extractor"]
    try:
        from transformers import ASTForAudioClassification, AutoFeatureExtractor
    except ImportError as exc:
        raise SfxUnavailable(
            f"오디오 분류에 필요한 패키지가 없습니다({exc}). "
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


def detect_sound_events(video: Path, speech: list[tuple[int, int]], duration_ms: int,
                        min_gap_ms: int = 1000, min_confidence: float = 0.3,
                        progress=None) -> list[SoundEvent]:
    """대사 없는 구간마다 오디오 분류 모델로 무슨 소리인지 짐작한다.

    **보고용이다.** 자막 Event로 만들거나 자동 반영하지 않는다 — 모듈 독스트링
    참고. 구간마다 ffmpeg으로 16kHz 모노 클립을 뽑아 모델에 넣고, 가장 확신
    높은 라벨 하나만 본다(top-1) — 여러 후보를 늘어놓기 시작하면 사람이 결국
    다 들어봐야 해서 이득이 없다.
    """
    import numpy as np
    import torch
    from scipy.io import wavfile

    say = progress or (lambda _m: None)
    model, extractor = _load_model()

    gaps = speech_gaps(speech, duration_ms, min_gap_ms)
    say(f"대사 없는 구간 {len(gaps)}곳에서 소리를 짐작합니다")

    events: list[SoundEvent] = []
    with tempfile.TemporaryDirectory(prefix="sfx_") as tmp:
        clip_path = Path(tmp) / "clip.wav"
        for start_ms, end_ms in gaps:
            result = subprocess.run(
                [_find("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", str(start_ms / 1000), "-i", _as_tool_path(video),
                 "-t", str((end_ms - start_ms) / 1000),
                 "-ac", "1", "-ar", "16000", "-vn", _as_tool_path(clip_path)],
                capture_output=True)
            if result.returncode != 0 or not clip_path.is_file():
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
            label = model.config.id2label[top_idx.item()]
            score = top_score.item()
            if score < min_confidence:
                continue
            events.append(SoundEvent(start_ms, end_ms, label, score,
                                     AUDIOSET_TO_CANDIDATE.get(label)))
    say(f"소리 후보 {len(events)}곳 찾음")
    return events


def sound_events_to_draft_events(events: list[SoundEvent], start_index: int = 1) -> list[Event]:
    """`candidate`가 있는 `SoundEvent`만 `kind="sfx"` `Event`로 바꾼다.

    매핑 없는 라벨(`candidate is None`)은 뺀다 — 원 라벨만으로 한국어 자막을
    지어내지 않는다(규칙3). 번호는 임시값이다(`merge_sound_events()`가 최종
    번호를 다시 매긴다) — `start_index`는 대사 이벤트 번호와 안 겹치게
    호출하는 쪽이 정한다.
    """
    mapped = [e for e in events if e.candidate]
    return [Event(start_index + i, e.start_ms, e.end_ms, e.candidate, kind="sfx")
           for i, e in enumerate(mapped)]


def merge_sound_events(dialogue_events: list[Event], dialogue_notes: list[tuple[int, str]],
                       sfx_events: list[Event],
                       ) -> tuple[list[Event], list[tuple[int, str]]]:
    """소리 후보(`Event`, `kind="sfx"`)를 대사 이벤트에 합친다. **순수 함수.**

    `merge_captions()`(`ocr.py`)와 구조는 같지만 노트 규칙이 다르다 — 여기서는
    **얹은 자리마다 예외 없이** "확인 필요"를 남긴다(모듈 독스트링 참고,
    OCR처럼 신뢰도로 가르지 않는다). 시간순으로 정렬하고 번호를 1..N으로
    다시 매기며, `dialogue_notes`도 새 번호로 옮긴다(안 옮기면 밀린 번호가
    엉뚱한 자막을 가리킨다).
    """
    dialogue_index_by_id = {id(e): e.index for e in dialogue_events}
    combined = sorted(dialogue_events + sfx_events, key=lambda e: e.start_ms)

    remap: dict[int, int] = {}
    sfx_notes: list[tuple[int, str]] = []
    for new_i, e in enumerate(combined, 1):
        if e.kind == "sfx":
            sfx_notes.append((new_i, "오디오 분류 추정 — 화면 보고 확인 필요"))
        else:
            remap[dialogue_index_by_id[id(e)]] = new_i
        e.index = new_i

    merged_notes = [(remap.get(i, i), msg) for i, msg in dialogue_notes] + sfx_notes
    return combined, merged_notes
