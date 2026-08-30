"""화면에 타 있는 캡션(그래픽 자막)을 읽는다.

`media.detect_bottom_text()`는 화면 아래에 글자가 "있는지"만 짐작하지 내용을
못 읽는다 — 정답 자막의 약 10%가 이런 화면 캡션이라 그것만으로는 못 채운다
(`docs/HANDOFF.md` 7절). 이 모듈이 실제로 글자를 읽는 다음 단계다.

**실제 인식은 격리 venv(`.venv-ocr`)의 서브프로세스가 한다.** EasyOCR이 torch를
요구하는데, `checker/diarize.py`가 pyannote.audio 때문에 이미 겪은 것과 같은
이유로 시스템 파이썬의 torch와 충돌할 수 있다(`docs/HANDOFF.md` 참고). 그래서
`_ocr_worker.py`를 격리 venv의 파이썬으로 실행해 결과만 JSON으로 받는다. 프레임
추출 자체는 ffmpeg 서브프로세스라 무거운 의존성이 없어 시스템 파이썬에서 한다.

**1단계: 추출+인식까지만.** 결과는 **보고용**이다 — 화면 글자 검출은 추정이다
(규칙 4, `detect_bottom_text`의 독스트링과 같은 이유). 자막 `Event`로 만들거나
파이프라인에 자동 반영하지 않는다. `Event` 병합·`forced_narrative` 서식 적용은
다음 단계로 미룬다(`docs/BACKLOG.md` 참고).

**실측 반영(2026-08-30, 예능A 19회 "Screwballs S02E19"로 스모크
테스트) — 구조 둘을 고침:**

1. `full_scan` 기본값을 **True로 바꿨다.** `detect_bottom_text()` 선필터(화면
   아래 25%만)로는 이 예능(캡션이 인물 옆 중앙~오른쪽, 세로 중간에 뜬다)에서
   캡션을 0개 찾았다 — 애초에 못 잡는 위치다. 규칙12("정확히 다 훑는 것이
   빠르게 끝내는 것보다 우선한다")를 그대로 따라 기본을 "느리지만 다 본다"로
   뒤집었다. 위치가 항상 화면 아래인 걸 아는 자료(공식 SDH 템플릿 등)에서만
   `--ocr-fast`로 예전 방식을 켠다.
2. `merge_frames`가 **편집 유사도**로 같은 캡션을 판정하게 바꿨다. 완전 일치만
   보면 압축·모션 블러로 프레임마다 한두 글자 흔들리는 실제 OCR 결과("마님"이
   "마남"·"마넘"으로 흔들림, 실측)가 매번 새 캡션으로 갈렸다.
"""

from __future__ import annotations

import difflib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .media import MediaToolUnavailable, _as_tool_path, _find, detect_bottom_text


class OcrUnavailable(Exception):
    """격리 venv(.venv-ocr)가 없거나, easyocr이 없거나, 서브프로세스가 실패했다."""


@dataclass
class OcrCaption:
    """화면 캡션 후보 하나. `frame_count`는 몇 프레임이 이 텍스트로 뭉쳤는지다."""

    start_ms: int
    end_ms: int
    text: str
    confidence: float
    frame_count: int = 1


def _find_ocr_python() -> Path:
    """격리 venv의 파이썬을 찾는다. `OCR_PYTHON`으로 다른 자리를 알려줄 수 있다."""
    override = os.environ.get("OCR_PYTHON")
    if override and Path(override).is_file():
        return Path(override)

    repo_root = Path(__file__).resolve().parent.parent
    candidates = [
        repo_root / ".venv-ocr" / "Scripts" / "python.exe",   # Windows
        repo_root / ".venv-ocr" / "bin" / "python",           # POSIX
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise OcrUnavailable(
        "화면 캡션 인식용 격리 환경(.venv-ocr)을 찾지 못했습니다. EasyOCR은 "
        "시스템 파이썬과 다른 torch 버전을 요구할 수 있어 별도 venv에 설치합니다"
        "(.venv-diarize와 같은 이유, docs/HANDOFF.md 참고):\n"
        "  python -m venv .venv-ocr\n"
        "  .venv-ocr/Scripts/python.exe -m pip install easyocr\n"
        "다른 자리에 있으면 OCR_PYTHON 환경변수로 python.exe 경로를 알려주세요.")


def _extract_frames(video: Path, spans: list[tuple[int, int]], sample_fps: float,
                    out_dir: Path) -> list[tuple[int, Path]]:
    """구간마다 프레임을 뽑는다. [(시각ms, 파일경로)] — 시각순."""
    step_ms = int(1000 / sample_fps)
    frames: list[tuple[int, Path]] = []
    for span_i, (start_ms, end_ms) in enumerate(spans):
        pattern = out_dir / f"span{span_i:03d}_%06d.png"
        result = subprocess.run(
            [_find("ffmpeg"), "-hide_banner", "-nostats",
             "-ss", f"{start_ms / 1000:.3f}", "-to", f"{end_ms / 1000:.3f}",
             "-i", _as_tool_path(video),
             "-vf", f"fps={sample_fps}", "-y", _as_tool_path(pattern)],
            capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            raise MediaToolUnavailable(
                f"프레임을 뽑지 못했습니다: {result.stderr.strip()[:200]}")
        for i, path in enumerate(sorted(out_dir.glob(f"span{span_i:03d}_*.png"))):
            frames.append((start_ms + i * step_ms, path))
    return frames


def _run_worker(frames: list[tuple[int, Path]], lang: str) -> list[tuple[int, str, float]]:
    """격리 venv에서 프레임마다 OCR을 돌린다. [(시각ms, 텍스트, 신뢰도)]."""
    if not frames:
        return []
    ocr_python = _find_ocr_python()
    worker = Path(__file__).with_name("_ocr_worker.py")

    with tempfile.TemporaryDirectory(prefix="stc-ocr-") as tmp:
        manifest = Path(tmp) / "frames.json"
        out_json = Path(tmp) / "results.json"
        manifest.write_text(
            json.dumps([[ms, str(path)] for ms, path in frames]), encoding="utf-8")
        result = subprocess.run(
            [str(ocr_python), str(worker), str(manifest), str(out_json), lang],
            capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0 or not out_json.is_file():
            detail = (result.stderr or "").strip()
            detail = detail[-500:] if detail else f"종료 코드 {result.returncode}"
            raise OcrUnavailable(f"화면 캡션 인식에 실패했습니다: {detail}")
        data = json.loads(out_json.read_text(encoding="utf-8"))
    return [(int(ms), str(text), float(conf)) for ms, text, conf in data]


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _similar(a: str, b: str, min_similarity: float) -> bool:
    """편집 유사도로 "같은 캡션이 흔들려 읽힌 것"과 "다른 캡션"을 가른다.

    `difflib.SequenceMatcher`(표준 라이브러리, 새 의존성 아님)의 비율을 쓴다.
    완전 일치만 보면 압축·모션 블러로 매 프레임 한두 글자씩 다르게 읽히는
    실제 OCR 결과가 계속 새 캡션으로 갈린다(실측, 2026-08-30 — "마님"이
    "마남"·"마넘"으로 흔들림, `docs/HANDOFF.md` 참고).
    """
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio() >= min_similarity


def merge_frames(results: list[tuple[int, str, float]], sample_step_ms: int,
                 min_confidence: float = 0.4, min_similarity: float = 0.6,
                 ) -> list[OcrCaption]:
    """프레임별 인식 결과를 캡션으로 묶는다. **순수 함수** — ffmpeg·easyocr 없이 테스트한다.

    인접 프레임(간격이 샘플 간격 이내)이 충분히 비슷한 텍스트(`_similar`, 완전
    일치가 아니라 편집 유사도)면 이어 붙인다. 유사도가 기준 미달이거나 간격이
    벌어지면 새 캡션으로 끊는다. 신뢰도 미달·빈 텍스트 프레임은 버린다.
    `media.detect_bottom_text()`의 연속-구간 병합과 같은 결이다.

    합쳐진 캡션의 대표 텍스트는 **그 안에서 신뢰도가 가장 높았던 프레임의
    텍스트**로 남긴다(다수결이 아니라 최고 신뢰도 — 프레임 몇 개짜리 짧은
    캡션에서도 다수결보다 값이 안정적이다).
    """
    kept = sorted(
        ((ms, text, conf) for ms, text, conf in results
         if conf >= min_confidence and text.strip()),
        key=lambda r: r[0],
    )
    captions: list[OcrCaption] = []
    for ms, text, conf in kept:
        text = text.strip()
        if (captions and ms - captions[-1].end_ms <= sample_step_ms
                and _similar(text, captions[-1].text, min_similarity)):
            last = captions[-1]
            last.end_ms = ms + sample_step_ms
            if conf > last.confidence:
                last.text = text
            last.confidence = (
                (last.confidence * last.frame_count + conf) / (last.frame_count + 1))
            last.frame_count += 1
        else:
            captions.append(OcrCaption(start_ms=ms, end_ms=ms + sample_step_ms,
                                       text=text, confidence=conf))
    return captions


def detect_onscreen_captions(video: Path, lang: str = "en", sample_fps: float = 2.0,
                             min_confidence: float = 0.4, min_similarity: float = 0.6,
                             full_scan: bool = True, engine=None) -> list[OcrCaption]:
    """화면 캡션을 읽는다. **보고용이다** — 규칙 4: 화면 글자 검출은 추정이다.

    `full_scan=True`(기본)면 영상 전체를 `sample_fps`로 고르게 훑는다 — 느리지만
    위치를 안 가린다. `full_scan=False`(`--ocr-fast`)면 `media.detect_bottom_text()`
    로 후보 구간부터 추려 비용을 줄이는 대신, 화면 아래 25% 바깥 캡션은 놓친다
    (실측, 2026-08-30: 이 선필터가 예능A 19회에서 캡션을 0개 찾았다 —
    캡션이 인물 옆 중앙~오른쪽에 뜨는 예능이었다). 위치가 항상 화면 아래인 걸
    아는 자료에서만 빠른 쪽을 쓴다.

    `engine`은 테스트에서 실제 EasyOCR 워커 대신 넣는 콜러블
    (`list[(ms, path)], lang -> list[(ms, text, conf)]`). 안 주면 `.venv-ocr`을 부른다.
    """
    if full_scan:
        from .media import probe
        info = probe(video)
        spans = [(0, info.duration_ms)]
    else:
        spans = detect_bottom_text(video, sample_fps=sample_fps)
    if not spans:
        return []

    run = engine or _run_worker
    with tempfile.TemporaryDirectory(prefix="stc-ocr-frames-") as tmp:
        frames = _extract_frames(video, spans, sample_fps, Path(tmp))
        results = run(frames, lang)

    return merge_frames(results, int(1000 / sample_fps), min_confidence, min_similarity)
