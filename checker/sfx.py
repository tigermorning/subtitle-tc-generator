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

**`--generate`에 자동으로 얹지 않는다.** `--sfx-scan`이 목록만 낸다 — OCR이
`--ocr-scan`(1단계, 보고용) 뒤에 `--generate --ocr`(2단계, 실제 병합)로 간
것과 같은 순서. 2단계는 이 1단계로 실제 검증한 뒤에 만든다.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .media import _as_tool_path, _find

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
