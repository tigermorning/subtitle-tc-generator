"""화면에 타 있는 캡션(그래픽 자막)을 읽는다.

`media.detect_bottom_text()`는 화면 아래에 글자가 "있는지"만 짐작하지 내용을
못 읽는다 — 정답 자막의 약 10%가 이런 화면 캡션이라 그것만으로는 못 채운다
(`docs/HANDOFF.md` 7절). 이 모듈이 실제로 글자를 읽는 다음 단계다.

**실제 인식은 격리 venv(`.venv-ocr`)의 서브프로세스가 한다.** EasyOCR이 torch를
요구하는데, `checker/diarize.py`가 pyannote.audio 때문에 이미 겪은 것과 같은
이유로 시스템 파이썬의 torch와 충돌할 수 있다(`docs/HANDOFF.md` 참고). 그래서
`_ocr_worker.py`를 격리 venv의 파이썬으로 실행해 결과만 JSON으로 받는다. 프레임
추출 자체는 ffmpeg 서브프로세스라 무거운 의존성이 없어 시스템 파이썬에서 한다.

**1단계: 추출+인식까지만.** `detect_onscreen_captions()`가 내는 결과는
**보고용**이다 — 화면 글자 검출은 추정이다(규칙 4, `detect_bottom_text`의
독스트링과 같은 이유). `--ocr-scan`은 이 결과를 출력만 하지 자막 `Event`로
바꾸지 않는다.

**2단계(2026-08-31): `captions_to_events()`·`merge_captions()`를 추가했다.**
`--generate --ocr`에서만 쓰인다 — `checker/position.py`의 `is_forced_narrative()`
가 이미 **텍스트 마커만으로** 화면자막을 알아보므로(`Event`에 새 필드 없이도
동작), 여기서 할 일은 마커를 입히고 대사 이벤트와 시간순으로 합쳐 번호를
다시 매기는 것뿐이다. 마커가 정해지지 않았으면(`ask`) 이 경로 자체를 막는다
(`checker/cli.py`의 `--ocr` 가드) — 마커 없이 합치면 방금 만든 캡션을 검사기가
못 알아본다.

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

**실측 반영 2회차(2026-08-31, 같은 영상 전체 회차 37분 재검증) — 가정 하나를
세웠다가 검증해서 절반만 맞고 절반은 틀렸다:**

1차 재검증에서 캡션 하나가 167초까지 늘어난 사례를 보고 "전이적 드리프트
(A~B~C~D로 비교 기준이 계속 옮겨가며 서로 다른 캡션이 이어 붙음)"로
가정하고, 비교 기준을 직전 캡션의 대표 텍스트 대신 **첫 프레임(anchor)**으로
바꾸고 `max_duration_ms`(당시 기본 8000ms)로 지속시간 상한도 걸었다.

**상한은 검증 없이 넣었다가 되돌렸다.** 문제의 167초 구간을 짧은 클립으로
잘라 재확인하고, 315초·340초 지점 프레임을 직접 열어 봤다 — "Sebastiam /
Tomy / Scarlet" **이름 캡션이 25초 넘게 픽셀 단위로 그대로**였다. 방송에서
이름표 캡션·정지 화면 코멘터리 캡션은 실제로 이 정도 오래 떠 있는다 — 167초
짜리는 버그가 아니라 **사실**이었다. `max_duration_ms` 기본값을 없앴다
(`None` = 상한 없음, 필요하면 `--ocr-max-duration`으로 사람이 켠다) — 증거
없이 상한을 두면 실제로 오래 떠 있는 정적 캡션(이름표·워터마크류)을
인위적으로 쪼갠다.

**anchor 비교는 남겼다.** 이건 합성 테스트(`tests/run_tests.py`)로 직접
확인한 실제 결함(A~B~C~D 드리프트로 완전히 다른 두 문장이 섞이는 경우)을
막는다 — 이 실제 영상에서 그런 사례가 확인된 것은 아니지만, 안 다치는
선에서 드는 안전장치라 남겨 뒀다. 상한처럼 "증거 없이 실측 결과를 인위적으로
바꾸는" 부작용이 없다(같은 텍스트가 반복되면 anchor와도 계속 비슷해 정상
병합된다 — 확인함).

**3단계(2026-08-31): `captions_to_draft_srt_events()`를 추가했다.**
`--ocr-hardsub`에서만 쓰인다 — 하드섭(화면 전체에 자막이 계속 타 있는 영상,
임베디드 자막 트랙이 아예 없는 경우) 전용. 2단계의 `captions_to_events`/
`merge_captions`과 달리 마커로 안 감싸고 카드 하나를 자막 하나로 그대로
옮긴다 — OCR 텍스트가 부가 캡션이 아니라 대사 그 자체이기 때문이다. 결과는
`tools/corpus_build.py:90-91`과 같은 이유로 **정답지가 아니다** — 사람이
영상과 대조해 고친 뒤에만 `학습한 TC 및 자막 모음/`에 들어간다
(`.claude/skills/정답지-학습/SKILL.md` 참고).

**4단계(2026-08-31, 같은 날): `refine_caption_boundaries()`를 추가했다.**
스모크 테스트(71분 하드섭 실측)에서 TC가 부정확하다는 지적을 받았다 — 굵은
샘플(`sample_fps=2.0`, 500ms 간격)로만 경계를 잡아서다. 처음엔 "음성(VAD)으로
다시 잡고 `align.py`로 텍스트를 얹자"고 제안했는데 **틀렸다** — 하드섭은 화면
픽셀에 이미 정확한 타이밍이 구워져 있어서, 음성 기준으로 바꾸면 화면 자막
고유의 편집 판단(최소 노출시간, 반응 시간)과 어긋나는 **덜 정확한 값으로
바꿔치기**하는 꼴이다(사용자와 논의해 확정). 맞는 방향은 **소리를 안 쓰고**
경계 앞뒤 한 스텝만 촘촘히(`refine_fps`) 다시 봐서 정확한 프레임을 찾는
것 — `media.edge_signal()`(`detect_bottom_text()`와 같은 계산)로 좁은 구간만
재고, `_find_transition()`으로 그 구간의 최저·최고 중간값을 넘는 지점을
찾는다. `--ocr-hardsub`에서만 기본으로 켠다.
"""

from __future__ import annotations

import difflib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .media import MediaToolUnavailable, _as_tool_path, _find, detect_bottom_text, edge_signal
from .model import Event
from .position import apply_marker


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
                    out_dir: Path, band: float | None = None) -> list[tuple[int, Path]]:
    """구간마다 프레임을 뽑는다. [(시각ms, 파일경로)] — 시각순.

    `band`를 주면 화면 아래 그 비율만 잘라서 읽는다(`media.detect_bottom_text`의
    자르기 계산과 똑같다 — `crop=iw:ih*band:0:ih*(1-band)`). **대사 하드섭
    전용이다** — 대사 자막은 관례상 항상 화면 아래 중앙에 뜨는데, 전체 프레임을
    읽으면 좌상단 작품명 워터마크·배경 간판 글자까지 섞여 카드 하나에 다 뭉친다
    (실측, 2026-08-31: 자르기 없이 돌렸더니 "모두가 자신의 무가치함과 싸우고
    있다" 워터마크가 대사 대신 계속 잡혔다). `--ocr-scan`/`--ocr`(예능 화면
    캡션, 위치가 안 정해짐)에는 안 쓴다 — 거긴 여전히 전체를 본다.
    """
    step_ms = int(1000 / sample_fps)
    crop = f",crop=iw:ih*{band}:0:ih*{1 - band}" if band else ""
    frames: list[tuple[int, Path]] = []
    for span_i, (start_ms, end_ms) in enumerate(spans):
        pattern = out_dir / f"span{span_i:03d}_%06d.png"
        result = subprocess.run(
            [_find("ffmpeg"), "-hide_banner", "-nostats",
             "-ss", f"{start_ms / 1000:.3f}", "-to", f"{end_ms / 1000:.3f}",
             "-i", _as_tool_path(video),
             "-vf", f"fps={sample_fps}{crop}", "-y", _as_tool_path(pattern)],
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
                 max_duration_ms: int | None = None) -> list[OcrCaption]:
    """프레임별 인식 결과를 캡션으로 묶는다. **순수 함수** — ffmpeg·easyocr 없이 테스트한다.

    인접 프레임(간격이 샘플 간격 이내)이 **그 캡션의 첫 프레임(anchor)과** 충분히
    비슷한 텍스트(`_similar`, 완전 일치가 아니라 편집 유사도)면 이어 붙인다.
    유사도가 기준 미달이거나 간격이 벌어지면 새 캡션으로 끊는다. 신뢰도 미달·
    빈 텍스트 프레임은 버린다. `media.detect_bottom_text()`의 연속-구간 병합과
    같은 결이다.

    **anchor와 비교하는 이유**: 직전 캡션의 "대표 텍스트"(신뢰도 최고 프레임 것,
    계속 갱신됨)와 비교하면 A~B~C~D처럼 인접한 것끼리만 비슷해도 A와 D는 전혀
    다른 문장이 될 때까지 계속 이어 붙는 전이적 드리프트가 생길 수 있다. 그룹의
    **첫 프레임**과 비교하면 이게 막힌다.

    **`max_duration_ms`는 기본으로 상한을 두지 않는다(`None`).** 처음엔 8000ms로
    막았다가 실측(2026-08-31, 예능A 19회)에서 되돌렸다 — 167초짜리로
    나온 캡션을 "버그"로 짐작했는데, 315초·340초 프레임을 직접 열어 보니 이름
    캡션("Sebastiam"/"Tomy"/"Scarlet")이 실제로 그만큼 안 바뀌고 떠 있었다.
    증거 없이 상한을 두면 실제로 오래 떠 있는 정적 캡션(이름표·워터마크류)을
    인위적으로 쪼갠다 — 필요하면 사람이 `--ocr-max-duration`으로 켠다.

    합쳐진 캡션의 대표 텍스트는 **그 안에서 신뢰도가 가장 높았던 프레임의
    텍스트**로 남긴다(다수결이 아니라 최고 신뢰도 — 프레임 몇 개짜리 짧은
    캡션에서도 다수결보다 값이 안정적이다). anchor 자체는 텍스트에 안 드러나고
    비교 기준으로만 쓴다.
    """
    kept = sorted(
        ((ms, text, conf) for ms, text, conf in results
         if conf >= min_confidence and text.strip()),
        key=lambda r: r[0],
    )
    captions: list[OcrCaption] = []
    anchors: list[str] = []
    for ms, text, conf in kept:
        text = text.strip()
        if (captions and ms - captions[-1].end_ms <= sample_step_ms
                and (max_duration_ms is None
                     or captions[-1].end_ms - captions[-1].start_ms < max_duration_ms)
                and _similar(text, anchors[-1], min_similarity)):
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
            anchors.append(text)
    return captions


def _find_transition(samples: list[tuple[float, float]], rising: bool) -> float | None:
    """표본 `[(초, 신호값)]` 안에서 min/max 중간값을 넘는 지점을 찾는다.

    통계 임계값(중앙값+편차)을 안 쓴다 — 구간이 좁아 표본이 몇 개뿐이라 의미가
    없다. 대신 **이 좁은 구간 안의 최저·최고 사이 중간**을 기준으로 삼는다.
    `rising=True`면 낮음→높음(시작 경계, 글자가 나타남), `False`면 높음→낮음
    (끝 경계, 글자가 사라짐)으로 본다. 변화가 없으면(장면이 그대로) `None`.
    """
    if len(samples) < 2:
        return None
    ordered = sorted(samples)
    values = [v for _, v in ordered]
    if max(values) - min(values) < 1e-9:
        return None
    threshold = (min(values) + max(values)) / 2
    for t, v in ordered:
        if rising and v >= threshold:
            return t
        if not rising and v < threshold:
            return t
    return None


def refine_caption_boundaries(video: Path, captions: list[OcrCaption], band: float | None,
                              step_ms: int, fps: float = 12.0,
                              signal=None) -> list[OcrCaption]:
    """캡션 시작·끝을 굵은 샘플 간격(`step_ms`) 안에서 촘촘히 다시 재서 정밀화한다.

    **소리를 안 쓴다.** 하드섭 자막은 화면 픽셀에 이미 정확한 타이밍이 구워져
    있다 — VAD(음성)로 다시 잡으면 화면 자막 고유의 편집 판단(최소 노출시간,
    반응 시간)과 안 맞아 오히려 부정확해진다(2026-08-31, 사용자와 논의해 확정).
    그래서 화면 신호(`media.edge_signal`, `detect_bottom_text`와 같은 계산)를
    경계 앞뒤 한 스텝만 `fps`로 다시 재서 정확한 프레임을 찾는다.

    시작은 `[start_ms - step_ms, start_ms]`(마지막으로 "없음"이 확실했던 지점
    부터 굵은 샘플이 "있음"을 잡은 지점까지)에서 상승 경계를, 끝은
    `[end_ms - step_ms, end_ms]`(마지막으로 "있음"이 확실했던 지점부터 굵은
    샘플이 "없어졌다"고 본 지점까지)에서 하강 경계를 찾는다. 못 찾으면(신호에
    변화가 없으면) 굵은 값을 그대로 둔다 — 정밀화 실패가 원래 값을 지우지
    않는다.

    `signal`은 테스트에서 `media.edge_signal` 대신 넣는 콜러블
    (`video, start_ms, end_ms, band, fps -> list[(초, 값)]`).
    """
    fetch = signal or edge_signal
    refined: list[OcrCaption] = []
    for c in captions:
        start_t = _find_transition(
            fetch(video, max(0, c.start_ms - step_ms), c.start_ms, band, fps), rising=True)
        end_t = _find_transition(
            fetch(video, max(0, c.end_ms - step_ms), c.end_ms, band, fps), rising=False)
        refined.append(OcrCaption(
            start_ms=int(start_t * 1000) if start_t is not None else c.start_ms,
            end_ms=int(end_t * 1000) if end_t is not None else c.end_ms,
            text=c.text, confidence=c.confidence, frame_count=c.frame_count))
    return refined


def detect_onscreen_captions(video: Path, lang: str = "en", sample_fps: float = 2.0,
                             min_confidence: float = 0.4, min_similarity: float = 0.6,
                             max_duration_ms: int | None = None, full_scan: bool = True,
                             band: float | None = None, refine: bool = False,
                             refine_fps: float = 12.0, engine=None) -> list[OcrCaption]:
    """화면 캡션을 읽는다. **보고용이다** — 규칙 4: 화면 글자 검출은 추정이다.

    `full_scan=True`(기본)면 영상 전체를 `sample_fps`로 고르게 훑는다 — 느리지만
    위치를 안 가린다. `full_scan=False`(`--ocr-fast`)면 `media.detect_bottom_text()`
    로 후보 구간부터 추려 비용을 줄이는 대신, 화면 아래 25% 바깥 캡션은 놓친다
    (실측, 2026-08-30: 이 선필터가 예능A 19회에서 캡션을 0개 찾았다 —
    캡션이 인물 옆 중앙~오른쪽에 뜨는 예능이었다). 위치가 항상 화면 아래인 걸
    아는 자료에서만 빠른 쪽을 쓴다.

    `band`(0~1)를 주면 화면 아래 그 비율만 잘라서 읽는다(`_extract_frames`
    참고) — `full_scan`과는 다른 축이다: `full_scan`은 **언제**(시간대) 볼지,
    `band`는 **어디**(화면 안 위치)를 볼지 정한다. 대사 하드섭(`--ocr-hardsub`)
    전용 — 좌상단 워터마크·배경 간판 글자가 안 섞인다. 위치가 안 정해진 예능
    화면 캡션(`--ocr-scan`/`--ocr`)에는 기본으로 안 쓴다(`band=None`, 전체 프레임).

    `refine=True`면 병합된 캡션의 시작·끝을 `refine_fps`로 촘촘히 다시 재서
    정밀화한다(`refine_caption_boundaries()` 참고) — **소리 안 씀**, 화면
    픽셀의 정확한 프레임을 찾는다. `--ocr-hardsub`(TC 정밀도가 중요한 하드섭
    정답지 초안)에서만 기본으로 켠다. `--ocr-scan`/`--ocr`(예능 화면 캡션,
    카드 경계가 하드섭만큼 깔끔하지 않음)은 기본 꺼짐.

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
        frames = _extract_frames(video, spans, sample_fps, Path(tmp), band=band)
        results = run(frames, lang)

    captions = merge_frames(results, int(1000 / sample_fps), min_confidence, min_similarity,
                            max_duration_ms)
    if refine and captions:
        captions = refine_caption_boundaries(
            video, captions, band, int(1000 / sample_fps), refine_fps)
    return captions


def captions_to_events(captions: list[OcrCaption], start_index: int = 1) -> list[Event]:
    """`OcrCaption` 목록을 `kind="caption"` `Event`로 바꾼다. 번역·마커 적용 **전**
    단계 — 인덱스는 임시값이다(`merge_captions()`가 최종 번호를 다시 매긴다).
    `start_index`는 대사 이벤트 번호와 안 겹치게 호출하는 쪽이 정한다.
    """
    return [Event(start_index + i, c.start_ms, c.end_ms, c.text, kind="caption")
            for i, c in enumerate(captions)]


def merge_captions(dialogue_events: list[Event], dialogue_notes: list[tuple[int, str]],
                   caption_events: list[Event], confidences: dict[int, float],
                   marker: str, note_below: float = 0.6,
                   ) -> tuple[list[Event], list[tuple[int, str]]]:
    """화면 캡션(`Event`, 아직 번역·마커 전)을 대사 이벤트에 합친다. **순수 함수.**

    - `position.apply_marker()`로 최종 텍스트를 만든다(그래야 `is_forced_narrative()`
      가 나중에 알아본다 — `Event.kind`는 검사 로직이 안 본다, 사람이 보는 부가
      정보일 뿐이다).
    - 시간순으로 정렬하고 번호를 1..N으로 다시 매긴다.
    - `dialogue_notes`(대사 쪽, `generate()`가 이미 만든 것)도 새 번호로 옮긴다
      — 안 옮기면 캡션이 끼어들며 밀린 번호가 엉뚱한 자막을 가리키게 된다.
    - `confidences`(임시 인덱스 -> 신뢰도)가 `note_below` 미만인 캡션은 "확인
      필요" 노트를 남긴다(규칙4 — 화면 글자 검출은 추정이니 표시만 하고 자동
      반영은 여기까지, 값 자체를 고치지 않는다).
    """
    marked = [Event(e.index, e.start_ms, e.end_ms, apply_marker(e.text, marker),
                    kind="caption") for e in caption_events]
    dialogue_index_by_id = {id(e): e.index for e in dialogue_events}
    combined = sorted(dialogue_events + marked, key=lambda e: e.start_ms)

    remap: dict[int, int] = {}
    caption_notes: list[tuple[int, str]] = []
    for new_i, e in enumerate(combined, 1):
        if e.kind == "caption":
            conf = confidences.get(e.index)
            if conf is not None and conf < note_below:
                caption_notes.append((new_i, f"OCR 인식(신뢰도 {conf:.2f}) — 확인 필요"))
        else:
            remap[dialogue_index_by_id[id(e)]] = new_i
        e.index = new_i

    merged_notes = [(remap.get(i, i), msg) for i, msg in dialogue_notes] + caption_notes
    return combined, merged_notes


def captions_to_draft_srt_events(captions: list[OcrCaption], min_confidence_note: float = 0.6,
                                 ) -> tuple[list[Event], list[tuple[int, str]]]:
    """OCR로 읽은 화면 캡션(카드 단위)을 자막 **초안** `Event`로 바꾼다.

    **정답지가 아니다.** `tools/corpus_build.py`의 원칙과 같다 — "OCR을 거친
    것은 타임코드도 글자도 근사값이 되므로 정답 자료로 쓰지 않는다"
    (`tools/corpus_build.py:90-91`). 하드섭(화면 전체에 자막이 타 있는 영상)처럼
    임베디드 자막 트랙이 아예 없어 `corpus_build.py`로 못 뽑을 때만 쓴다 — 사람이
    영상과 대조해 고친 뒤에야 `.claude/skills/정답지-학습/`의 §4 이후(원본 그대로
    `학습한 TC 및 자막 모음/`에 복사)를 밟을 수 있다.

    `captions_to_events()`/`merge_captions()`(2단계 — whisper 대사 위에 얹는
    부가 캡션용, 마커로 감싸고 다른 draft와 병합함)와는 **다른 함수**다. 여기선
    OCR 텍스트가 대사 그 자체이므로 마커를 안 감싸고 카드 하나 = 자막 하나로
    그대로 옮긴다.

    신뢰도가 `min_confidence_note` 미만인 카드는 노트로 남긴다(규칙4 — 알리기만
    하고 자동으로 고치지 않는다).
    """
    events = [Event(i, c.start_ms, c.end_ms, c.text, kind="caption")
             for i, c in enumerate(captions, 1)]
    notes = [(i, f"OCR 신뢰도 {c.confidence:.2f} — 영상과 대조해 확인")
            for i, c in enumerate(captions, 1) if c.confidence < min_confidence_note]
    return events, notes
