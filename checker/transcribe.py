"""영상에서 자막을 만든다 — ffmpeg에 내장된 whisper로.

ffmpeg 9.0부터 `whisper` 필터가 들어 있다(`--enable-whisper`). 별도 도구를 깔 필요
없이 방금 쓰던 그 ffmpeg으로 전사가 된다. **원고가 밖으로 나가지 않는다.**

**글자 수는 여기서 제한하지 않는다.** 필터에 `max_len`이 있지만 쓰지 않는다 —
전사 단계에서 글자 수를 자르면 문장이 부서진 채로 굳는다. 사람이 하는 순서대로,
전사는 자유롭게 하고 재단은 뒤(`resplit.py` -> `timing.py`)에서 한다.

모델 크기가 결과를 가른다. 같은 60초 구간 실측(RTX 3060 Ti):

    ggml-base (141MB, CPU)          7.8배속   "동기와 설명" "그 석태들 기본강에서"
    ggml-large-v3-turbo (1.5GB, GPU) 23.1배속  "동기화 설명" "그 서프트웨어 기본강의에서"

큰 모델이 **더 빠르다** — GPU가 붙기 때문이다. 품질을 낮출 이유가 없다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .align import Segment
from .media import MediaToolUnavailable, _find, _known_places

TIMECODE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


def find_model(explicit: str | None = None) -> Path:
    """모델 파일을 찾는다. 없으면 어디서 받는지 알려 준다."""
    candidates = [explicit, os.environ.get("WHISPER_MODEL")]
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value)

    # 흔히 두는 자리들(`paths.model_dirs`). **사용자 자료 자리가 먼저다** — 실행
    # 파일을 다시 만들면 프로그램 폴더는 지워지지만 그 자리는 남는다.
    from .paths import model_dirs

    for folder in model_dirs():
        if folder.is_dir():
            found = sorted(folder.glob("ggml-*.bin"))
            if found:
                # large > medium > small > base 순으로 큰 것을 고른다
                found.sort(key=lambda p: p.stat().st_size, reverse=True)
                return found[0]

    raise MediaToolUnavailable(
        "whisper 모델(ggml-*.bin)을 찾지 못했습니다. WHISPER_MODEL 환경변수로 경로를 "
        "지정하거나 models/ 폴더에 두세요. "
        "https://huggingface.co/ggerganov/whisper.cpp 에서 받을 수 있습니다"
        "(ggml-large-v3-turbo.bin 권장, 1.5GB)."
    )


def _parse_srt(text: str) -> list[Segment]:
    segments: list[Segment] = []
    for block in re.split(r"\n{2,}", text.replace("\r\n", "\n")):
        lines = [l for l in block.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        found = next((TIMECODE.search(l) for l in lines if TIMECODE.search(l)), None)
        if not found:
            continue
        g = [int(x) for x in found.groups()]
        start = (g[0] * 3600 + g[1] * 60 + g[2]) * 1000 + g[3]
        end = (g[4] * 3600 + g[5] * 60 + g[6]) * 1000 + g[7]
        body = "\n".join(lines[lines.index(found.string) + 1:]).strip()
        if body:
            segments.append(Segment(start, end, body))
    return segments


_WHISPER_FFMPEG: list = []


def ffmpeg_with_whisper() -> str:
    """whisper 필터가 **들어 있는** ffmpeg을 찾는다.

    `whisper` 필터는 ffmpeg 9.0부터, 그것도 `--enable-whisper`로 빌드한 것에만
    있다. Subtitle Edit이 딸려 보내는 ffmpeg은 8.0이라 없다(실측). 아무 ffmpeg이나
    잡아 쓰면 "전사 실패"라는 말만 나오고 왜인지 알 수 없다.
    """
    if _WHISPER_FFMPEG:
        return _WHISPER_FFMPEG[0]

    candidates = []
    try:
        candidates.append(_find("ffmpeg"))
    except MediaToolUnavailable:
        pass
    candidates += [str(p) for p in _known_places("ffmpeg") if p.is_file()]

    for exe in dict.fromkeys(candidates):
        try:
            out = subprocess.run([exe, "-hide_banner", "-filters"],
                                 capture_output=True, text=True, timeout=30,
                                 encoding="utf-8", errors="replace").stdout or ""
        except (OSError, subprocess.SubprocessError):
            continue
        if re.search(r"^\s*\S+\s+whisper\s", out, re.MULTILINE):
            _WHISPER_FFMPEG.append(exe)
            return exe

    raise MediaToolUnavailable(
        "whisper 필터가 있는 ffmpeg을 찾지 못했습니다. 9.0 이상이 필요합니다"
        "(Subtitle Edit이 딸려 보내는 8.0에는 없습니다).\n"
        "  winget install Gyan.FFmpeg\n"
        "설치 뒤에도 못 찾으면 FFMPEG_PATH로 경로를 알려 주세요.")


def _drive_root(path: Path) -> str:
    """WSL에서 이 경로가 어느 드라이브에 있는지. 드라이브가 다르면 상대 경로가 깨진다."""
    parts = path.resolve().parts
    return "/".join(parts[:3]) if len(parts) >= 3 and parts[1] == "mnt" else ""


def _filter_path(target: Path, work: Path) -> str:
    """필터 옵션에 넣을 수 있는 경로를 만든다.

    **절대 경로를 쓸 수 없다.** ffmpeg 필터 문법에서 `:`는 옵션 구분자라
    `C:/...`가 옵션 이름으로 읽히고, `C\\:/...`로 이스케이프해도 파싱이 깨진다
    (ffmpeg 9.0 실측). 그래서 작업 폴더 기준 **상대 경로**로만 부른다.

    드라이브가 다르면 상대 경로가 `../../mnt/d/...`가 되는데 Windows 쪽 ffmpeg은
    이걸 못 푼다. 그럴 때만 작업 폴더로 복사한다.
    """
    if _drive_root(target) != _drive_root(work):
        copied = work / target.name
        if not copied.exists():
            shutil.copy2(target, copied)
        return copied.name
    return os.path.relpath(target.resolve(), work.resolve()).replace(os.sep, "/")


def _ascii_model_path(model_path: Path, work: Path) -> str:
    """모델을 **아스키 이름으로** 부를 수 있게 만든다.

    **whisper는 한글이 든 경로의 모델을 못 연다**(2026-08-12 재현). ffmpeg 자체는
    유니코드 경로를 잘 다루지만, 필터 안의 whisper.cpp는 모델을 옛 `fopen`으로
    열어서 Windows 코드페이지에 없는 글자가 있으면 실패한다:

        whisper_init_from_file_with_params_no_state: failed to open
        '../../../../AppData/Roaming/자막편집기/models/ggml-large-v3-turbo.bin'
        Error opening output files: I/O error

    사용자 자료 폴더 이름이 `자막편집기`라서 **기본 설치 상태에서 바로 걸린다.**
    "영상에서 자막 만들기를 눌러도 아무 일이 없다"는 신고의 원인이 이것이다.

    고치는 방법은 **하드링크**다. 같은 드라이브면 자료를 복사하지 않으므로 1.6GB
    모델도 즉시 끝난다. 드라이브가 다르거나 파일 체계가 하드링크를 막으면 그때만
    복사한다 — 느리다는 것을 말해 주고 한다.
    """
    relative = _filter_path(model_path, work)
    if relative.isascii():
        return relative

    link = work / "model.bin"
    if link.exists():
        return link.name
    try:
        os.link(model_path, link)
    except OSError:
        shutil.copy2(model_path, link)
    return link.name


def _ms_to_srt(ms: int) -> str:
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


_FASTER_WHISPER_MODEL_CACHE: dict = {}


def _faster_whisper_transcribe(video: Path, language: str, use_gpu: bool,
                               say) -> list[Segment] | None:
    """faster-whisper(ctranslate2)로 전사한다. **신뢰도(`avg_logprob`)를 준다** —

    ffmpeg의 whisper 필터는 srt·json 어느 출력도 신뢰도를 안 준다(2026-08-30
    직접 확인). 신뢰도가 있어야 환각(잡음 구간에서 whisper가 뜻 없는 글자를
    지어내는 것)을 문자 밀도 어림 대신 정확히 잡을 수 있다(`generate.py`의
    환각 의심 자막 경고 참고).

    패키지가 없거나 모델을 못 불러오면 `None`을 돌려준다 — 호출부가 기존
    ffmpeg 방식으로 조용히 넘어간다(**말없이 실패하지 않는다** — `say`로
    알린다).
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None

    key = (use_gpu,)
    fw_model = _FASTER_WHISPER_MODEL_CACHE.get(key)
    if fw_model is None:
        try:
            device = "cuda" if use_gpu else "cpu"
            compute_type = "float16" if use_gpu else "int8"
            say(f"faster-whisper 모델을 불러옵니다({device}, 처음엔 몇십 초 걸릴 수 있습니다)...")
            fw_model = WhisperModel(
                os.environ.get("FASTER_WHISPER_MODEL", "large-v3-turbo"),
                device=device, compute_type=compute_type)
            _FASTER_WHISPER_MODEL_CACHE[key] = fw_model
        except Exception as exc:  # noqa: BLE001 - 모델 로드 실패 경로가 다양하다
            say(f"faster-whisper 모델을 못 불러왔습니다({exc}) — 기존 방식으로 돌립니다")
            return None

    try:
        raw_segments, _info = fw_model.transcribe(
            str(video), language=None if language == "auto" else language,
            vad_filter=False)
        out = []
        for seg in raw_segments:
            text = seg.text.strip()
            if text:
                out.append(Segment(int(seg.start * 1000), int(seg.end * 1000),
                                   text, confidence=seg.avg_logprob))
        return out
    except Exception as exc:  # noqa: BLE001
        say(f"faster-whisper 전사가 실패했습니다({exc}) — 기존 방식으로 돌립니다")
        return None


def transcribe(video: Path, language: str = "auto", model: str | None = None,
               use_gpu: bool = True, progress=None,
               keep: Path | None = None, cache: Path | None = None) -> list[Segment]:
    """영상에서 말소리를 받아 적는다. 세그먼트 목록을 돌려준다.

    **faster-whisper가 있으면 그것을 먼저 쓴다**(2026-08-30) — 신뢰도를 주는
    유일한 경로다. 없거나 실패하면 ffmpeg 내장 whisper 필터로 돌아간다(신뢰도
    없이, `Segment.confidence`가 `None`).

    `keep`을 주면 전사 SRT를 그 자리에 남긴다 — 뒤 단계가 틀렸을 때 전사까지
    다시 돌리지 않기 위해서다(긴 영상에서 이 차이가 크다). **신뢰도는 SRT에
    못 담아 이 사본엔 안 남는다.**

    `cache`를 주면 **있으면 읽고, 없으면 전사한 뒤 만든다.** 코퍼스 재검사·상한값
    재조정(`tools/calibrate_regroup.py`)처럼 같은 영상을 여러 번 다시 훑을 때
    whisper를 매번 새로 돌리지 않기 위해서다(2026-08-29, 예능A 15·16회
    상한값 스윕에서 매번 수 분씩 걸려 실측함). `keep`과 달리 **이미 있으면 절대
    덮어쓰지 않는다** — 디버그용 사본이 아니라 재사용 대상이기 때문이다.
    **캐시에서 읽으면 신뢰도가 없다** — SRT를 거치기 때문이다.
    """
    say = progress or (lambda _m: None)
    video = Path(video)
    if not video.is_file():
        raise MediaToolUnavailable(f"영상을 찾지 못했습니다: {video}")

    if cache and Path(cache).is_file():
        say(f"전사 캐시를 재사용합니다 — {cache}")
        return _parse_srt(Path(cache).read_text(encoding="utf-8", errors="replace"))

    fw_segments = _faster_whisper_transcribe(video, language, use_gpu, say)
    if fw_segments is not None:
        say(f"전사 완료 — 세그먼트 {len(fw_segments)}개(faster-whisper)")
        if keep or cache:
            srt_text = "\n\n".join(
                f"{i}\n{_ms_to_srt(s.start_ms)} --> {_ms_to_srt(s.end_ms)}\n{s.text}"
                for i, s in enumerate(fw_segments, 1))
            if keep:
                Path(keep).write_text(srt_text, encoding="utf-8")
            if cache:
                Path(cache).parent.mkdir(parents=True, exist_ok=True)
                Path(cache).write_text(srt_text, encoding="utf-8")
        return fw_segments

    model_path = find_model(model)

    # 작업 폴더는 영상 옆에 둔다 — 상대 경로가 짧아지고 드라이브가 같아진다.
    work = video.resolve().parent / ".subtitle-tc-generator-work"
    work.mkdir(exist_ok=True)
    out_name = "transcript.srt"
    try:
        say(f"전사 중입니다 — 모델 {model_path.name}"
            f"{'(GPU)' if use_gpu else '(CPU)'}. 영상 길이에 비례해 걸립니다...")
        result = subprocess.run(
            [ffmpeg_with_whisper(), "-hide_banner", "-nostats",
             "-i", _filter_path(video, work), "-vn",
             "-af", (f"whisper=model={_ascii_model_path(model_path, work)}"
                     f":language={language}:format=srt:destination={out_name}"
                     f":queue=10:use_gpu={'true' if use_gpu else 'false'}"),
             "-f", "null", "-"],
            cwd=work, capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
        )
        srt_path = work / out_name
        if not srt_path.is_file():
            noise = ((result.stderr or "") + (result.stdout or "")).strip()
            tail = (noise.splitlines() or ["원인 불명"])[-1]
            raise MediaToolUnavailable(f"전사에 실패했습니다: {tail[:200]}")
        raw = srt_path.read_text(encoding="utf-8", errors="replace")
        if keep:
            Path(keep).write_text(raw, encoding="utf-8")
        if cache:
            Path(cache).parent.mkdir(parents=True, exist_ok=True)
            Path(cache).write_text(raw, encoding="utf-8")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    segments = _parse_srt(raw)
    say(f"전사 완료 — 세그먼트 {len(segments)}개")
    return segments
