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

**4단계(2026-08-31) — "경계만 따로 정밀화"를 세 번 고치다가 결국 통째로
걷어냈다. 순서대로 남긴다(다음에 같은 길을 또 걷지 않도록):**

1. **1차**: 굵은 샘플(2fps, 500ms 간격)로만 경계를 잡으니 TC가 부정확하다는
   실사용 지적을 받았다. "음성(VAD)으로 다시 잡고 `align.py`로 텍스트를
   얹자"고 제안했는데 **틀렸다** — 하드섭은 화면 픽셀에 이미 정확한 타이밍이
   구워져 있어서, 음성 기준으로 바꾸면 화면 자막 고유의 편집 판단(최소
   노출시간, 반응 시간)과 어긋나는 덜 정확한 값으로 바꿔치기하는 꼴이다.
   대신 경계 앞뒤 한 스텝만 윤곽선 밀도(`media.edge_signal`, `detect_
   bottom_text`와 같은 계산)로 촘촘히 다시 쟀다.
2. **2차**: 71분 전체로 재실측해 SE에서 파형과 대조하니 여전히 하나도 안
   맞고, 인접 캡션끼리 겹치기까지 했다. 윤곽선 밀도가 클로즈업 영상에서
   배우 얼굴·옷깃·손에 반응한 것이 원인이었다 — 자막이 아닌 것에도 반응하는
   방법이었다. "자막이 뜬 시간을 읽으면 TC가 잡히는 것 아니냐"는 지적이
   맞았고, 경계 재확인을 실제 OCR 재확인으로 바꿨다(모든 캡션의 경계 창을
   모아 한 번의 OCR 호출로). 겹침 방지(`_enforce_no_overlap`, 지금도 씀)도
   이때 추가했다.
3. **3차, 최종**: 그런데도 실측(같은 25초 클립)에서 정밀화가 거의 매번
   "못 찾음"으로 굵은 값을 그대로 돌려줬다. 프레임을 직접 저장해 열어보고
   원인을 찾았다 — **같은 시각(8.5초)인데 연속 디코딩한 프레임엔 자막이
   보이고, 경계만 따로 좁게 seek해서 뽑은 프레임엔 안 보였다**(3초 웜업을
   줘도 똑같았다). ffmpeg이 `-ss`로 짧은 구간을 독립적으로 seek하면 실제
   내용과 다른 프레임을 준다 — 이 프로젝트가 이미 알고 있던 문제
   (`_extract_frames`의 pts_time 관련 주석 참고)의 또 다른 얼굴이었다.
   **"경계만 따로 정밀화"라는 설계 자체가 ffmpeg 특성상 성립하지 않는다**
   — `refine_caption_boundaries`/`_apply_boundary_refinements`/
   `_find_transition`/`media.edge_signal`을 전부 걷어냈다.

**최종 해법**: 애초에 seek를 안 하는 연속 디코딩(`full_scan`의 굵은 패스가
이미 하던 방식, 이미 정확하다고 실측으로 확인됨)을 **그대로 촘촘한 fps로**
돌린다. 새 방법을 시도하는 게 아니라 이미 검증된 방법의 해상도만 올린 것 —
`--ocr-hardsub`의 `sample_fps` 기본값을 12(83ms 간격)로 올렸다. 6배 느리지만
(71분 영상 기준 75분 -> 대략 7~8시간), 시간보다 TC 정확도가 중요하다는
사용자 결정에 따른 것이다. `_enforce_no_overlap()`만 남겨서 항상 적용한다.
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


def _run_worker(frames: list[tuple[int, Path]], lang: str,
                checkpoint_path: Path | None = None) -> list[tuple[int, str, float]]:
    """격리 venv에서 프레임마다 OCR을 돌린다. [(시각ms, 텍스트, 신뢰도)].

    `checkpoint_path`를 주면 결과를 임시 폴더 대신 그 경로에 직접 쌓는다 —
    `_ocr_worker.py`가 프레임마다 그 파일에 바로 남기므로, 중간에 끊겨도
    같은 경로로 다시 부르면 이미 된 프레임은 다시 안 돌고 이어서 돈다.
    이 경로가 지금 스캔(영상·설정)에 맞는 체크포인트인지는 부르는 쪽
    (`detect_onscreen_captions`)이 미리 확인한다 — 여기서는 그냥 쓴다.
    """
    if not frames:
        return []
    ocr_python = _find_ocr_python()
    worker = Path(__file__).with_name("_ocr_worker.py")

    with tempfile.TemporaryDirectory(prefix="stc-ocr-") as tmp:
        manifest = Path(tmp) / "frames.json"
        out_json = checkpoint_path if checkpoint_path is not None else Path(tmp) / "results.json"
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
            # **체크포인트는 여기서 안 지운다.** 실패해도 워커가 프레임마다
            # 이미 디스크에 남긴 진행 상황이 `out_json`(=`checkpoint_path`)에
            # 그대로 있다 — 다음에 같은 인자로 다시 부르면 그 자리부터 이어간다.
            raise OcrUnavailable(f"화면 캡션 인식에 실패했습니다: {detail}")
        data = json.loads(out_json.read_text(encoding="utf-8"))
    return [(int(ms), str(text), float(conf)) for ms, text, conf in data]


def _checkpoint_fingerprint(video: Path, lang: str, sample_fps: float,
                            band: float | None, full_scan: bool) -> dict:
    """이 스캔을 다시 알아볼 수 있는 값들. 하나라도 바뀌면 예전 체크포인트를 못 믿는다.

    영상은 **크기+수정시각**으로 식별한다(경로만 보면 같은 이름의 다른
    영상으로 갈아치워진 것을 못 잡는다).
    """
    stat = video.stat()
    return {"video": str(Path(video).resolve()), "video_size": stat.st_size,
            "video_mtime": stat.st_mtime, "lang": lang, "sample_fps": sample_fps,
            "band": band, "full_scan": full_scan}


def _prepare_checkpoint(checkpoint_path: Path, fingerprint: dict) -> None:
    """체크포인트가 지금 설정과 안 맞으면 지운다 — 이어받을 자격이 없다.

    지문은 결과 파일 옆에 `<이름>.meta.json`으로 따로 둔다. `_ocr_worker.py`가
    쓰는 결과 파일 형식(`[[ms, text, conf], ...]`)은 안 건드린다 — 지문
    검증은 순전히 이 파일(`ocr.py`) 몫이다.
    """
    meta_path = checkpoint_path.with_name(checkpoint_path.name + ".meta.json")
    stored = None
    if meta_path.is_file():
        try:
            stored = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = None
    if stored != fingerprint and checkpoint_path.is_file():
        checkpoint_path.unlink()
    meta_path.write_text(json.dumps(fingerprint), encoding="utf-8")


def _cleanup_checkpoint(checkpoint_path: Path) -> None:
    """스캔이 끝까지 성공하면 체크포인트를 치운다.

    남겨 두면 다음 실행이 "이전 체크포인트를 이어받는다"고 믿어 버린다 —
    사실은 완전히 새 스캔인데 우연히 지문(영상·설정)이 같은 경우다(같은
    영상을 일부러 다시 스캔하는 경우 등). 끊긴 실행만 이어받게 하려면,
    다 끝난 체크포인트는 그 자리에서 지워야 한다.
    """
    meta_path = checkpoint_path.with_name(checkpoint_path.name + ".meta.json")
    for p in (checkpoint_path, meta_path):
        try:
            p.unlink()
        except OSError:
            pass


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


def _enforce_no_overlap(captions: list[OcrCaption]) -> list[OcrCaption]:
    """인접한 캡션끼리 시간이 겹치지 않게 한다(실사용 지적, 2026-08-31 —
    경계를 캡션마다 독립적으로 정밀화하다 보니 앞 캡션 끝이 뒤 캡션 시작보다
    늦게 잡히는 경우를 안 막고 있었다). 뒤 캡션 시작이 앞 캡션 끝보다 빠르면
    앞 캡션 끝을 뒤 캡션 시작으로 당긴다.
    """
    ordered = sorted(captions, key=lambda c: c.start_ms)
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.end_ms > cur.start_ms:
            prev.end_ms = max(prev.start_ms, cur.start_ms)
    return ordered


def detect_onscreen_captions(video: Path, lang: str = "en", sample_fps: float = 2.0,
                             min_confidence: float = 0.4, min_similarity: float = 0.6,
                             max_duration_ms: int | None = None, full_scan: bool = True,
                             band: float | None = None, engine=None,
                             checkpoint_path: Path | None = None) -> list[OcrCaption]:
    """화면 캡션을 읽는다. **보고용이다** — 규칙 4: 화면 글자 검출은 추정이다.

    `full_scan=True`(기본)면 영상 전체를 **처음부터 끝까지 안 끊고**
    `sample_fps`로 고르게 훑는다 — 느리지만 위치를 안 가리고, ffmpeg이 seek
    없이 연속으로 디코딩하므로 프레임 내용이 정확하다(실측으로 확인됨, 아래
    "정밀화를 걷어낸 이유" 참고). `full_scan=False`(`--ocr-fast`)면
    `media.detect_bottom_text()`로 후보 구간부터 추려 비용을 줄이는 대신,
    화면 아래 25% 바깥 캡션은 놓친다(실측, 2026-08-30: 이 선필터가 예능A
    시즌2 19회에서 캡션을 0개 찾았다 — 캡션이 인물 옆 중앙~오른쪽에 뜨는
    예능이었다). 위치가 항상 화면 아래인 걸 아는 자료에서만 빠른 쪽을 쓴다.

    `band`(0~1)를 주면 화면 아래 그 비율만 잘라서 읽는다(`_extract_frames`
    참고) — `full_scan`과는 다른 축이다: `full_scan`은 **언제**(시간대) 볼지,
    `band`는 **어디**(화면 안 위치)를 볼지 정한다. 대사 하드섭(`--ocr-hardsub`)
    전용 — 좌상단 워터마크·배경 간판 글자가 안 섞인다. 위치가 안 정해진 예능
    화면 캡션(`--ocr-scan`/`--ocr`)에는 기본으로 안 쓴다(`band=None`, 전체 프레임).

    **TC 정밀도가 필요하면 `sample_fps`를 올린다 — "경계만 따로 정밀화"는
    없다.** 한때 굵게 훑고 경계 근처만 따로 촘촘히 다시 seek해서 재확인하는
    방법을 만들었다가 걷어냈다(`checker/ocr.py`의 모듈 독스트링 "4단계" 참고)
    — ffmpeg이 짧은 구간을 독립적으로 seek하면 실제 내용과 다른 프레임을
    준다는 게 실측으로 드러났다(같은 시각인데 연속 디코딩 프레임엔 자막이
    보이고 독립 seek 프레임엔 안 보임, 3초 웜업을 줘도 마찬가지). seek 없이
    연속으로 디코딩하는 것만 믿을 수 있어서, `--ocr-hardsub`는 `sample_fps`
    기본값을 12로 올려 이 함수를 그대로(더 촘촘하게) 쓴다.

    결과는 항상 인접 캡션끼리 겹치지 않게 정리한다(`_enforce_no_overlap`).

    `engine`은 테스트에서 실제 EasyOCR 워커 대신 넣는 콜러블
    (`list[(ms, path)], lang -> list[(ms, text, conf)]`). 안 주면 `.venv-ocr`을 부른다.

    **이어하기(2026-08-31)**: `checkpoint_path`를 주면 워커가 프레임마다
    결과를 그 경로에 바로 남긴다(`_run_worker`·`_ocr_worker.py` 참고) —
    `--ocr-hardsub`(71분 영상 기준 7~8시간짜리 스캔)처럼 오래 걸리는 호출이
    중간에 끊겨도(절전·재부팅·강제 종료) 같은 인자로 다시 부르면 이미 된
    프레임은 다시 안 돌고 이어서 돈다. 지금 (영상·언어·fps·band·full_scan)
    조합과 다른 체크포인트는 지우고 새로 시작한다(`_prepare_checkpoint`) —
    다른 영상이나 다른 설정의 옛 결과를 이어받는 사고를 막는다. 스캔이
    끝까지 성공하면 체크포인트는 치운다(`_cleanup_checkpoint`) — 남겨 두면
    다음 실행이 그 완료된 파일을 "이어받는다"고 오해한다. 안 주면(기본)
    예전처럼 끊기면 처음부터 다시 돈다.
    """
    if full_scan:
        from .media import probe
        info = probe(video)
        spans = [(0, info.duration_ms)]
    else:
        spans = detect_bottom_text(video, sample_fps=sample_fps)
    if not spans:
        return []

    use_checkpoint = checkpoint_path is not None and engine is None
    if use_checkpoint:
        fingerprint = _checkpoint_fingerprint(video, lang, sample_fps, band, full_scan)
        _prepare_checkpoint(checkpoint_path, fingerprint)

    run = engine or (lambda fr, lg: _run_worker(fr, lg, checkpoint_path))
    with tempfile.TemporaryDirectory(prefix="stc-ocr-frames-") as tmp:
        frames = _extract_frames(video, spans, sample_fps, Path(tmp), band=band)
        results = run(frames, lang)

    if use_checkpoint:
        _cleanup_checkpoint(checkpoint_path)

    captions = merge_frames(results, int(1000 / sample_fps), min_confidence, min_similarity,
                            max_duration_ms)
    if captions:
        captions = _enforce_no_overlap(captions)
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
