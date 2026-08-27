"""`--generate`를 실행하기 전에 환경이 준비됐는지 미리 본다.

**오늘 실제로 겪은 실패들**(2026-08-27) — torch 버전 충돌로 화자 분리가
죽음, ffmpeg 공유 라이브러리(DLL)를 못 찾음, 디스크 여유 공간 3MB, HF 토큰
없음, Ollama 서버 응답 없음 — 이 전부 전사·번역을 10~20분 돌리고 나서야
드러났다. 여기서 하는 점검은 **환경·의존성**만 본다.

**이 점검이 못 잡는 것**: 실제 번역 품질, TC 재분할·스포팅 로직의 버그,
whisper 환청, 화자 분리 판단의 정확도 — 이런 것은 실행해 봐야만 나온다.
`--dry-run`을 통과했다고 결과가 옳다는 뜻이 아니다. **속도(빨리 실패를
안다) 문제이지 정확도(로직이 맞다) 문제가 아니다** — 둘을 섞어 말하지 않는다.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def run(video, profile: dict | None = None, translate: bool = False,
       diarize: bool = False, speech_method: str = "auto",
       translate_model: str | None = None, whisper_model: str | None = None,
       min_free_gb: float = 2.0) -> list[Check]:
    """환경 점검 목록을 돌려준다. 예외를 올리지 않는다 — 실패도 결과다."""
    checks: list[Check] = []
    video = Path(video)

    from .media import MediaToolUnavailable, probe
    if not video.is_file():
        checks.append(Check("영상 파일", False, f"찾지 못했습니다: {video}"))
    else:
        try:
            info = probe(video)
            checks.append(Check("영상 파일", True,
                                f"{info.duration_ms / 1000:.0f}초, {info.fps:.3f}fps"))
        except MediaToolUnavailable as exc:
            checks.append(Check("영상 파일", False, str(exc)))

    from .transcribe import ffmpeg_with_whisper, find_model as find_whisper_model
    try:
        ffmpeg_with_whisper()
        checks.append(Check("ffmpeg(whisper 필터)", True))
    except MediaToolUnavailable as exc:
        checks.append(Check("ffmpeg(whisper 필터)", False, str(exc)))
    try:
        model_path = find_whisper_model(whisper_model)
        checks.append(Check("whisper 모델", True, str(model_path)))
    except MediaToolUnavailable as exc:
        checks.append(Check("whisper 모델", False, str(exc)))

    if speech_method in ("auto", "vad"):
        from .vad import VadUnavailable, find_model as find_vad_model
        try:
            find_vad_model()
            checks.append(Check("VAD 모델", True))
        except VadUnavailable as exc:
            # auto는 없으면 음량 검출로 조용히 넘어가므로 실패로 안 본다 —
            # media.find_speech()가 이미 그렇게 설계돼 있다.
            if speech_method == "auto":
                checks.append(Check("VAD 모델", True, "없음 — 음량 검출로 대신함"))
            else:
                checks.append(Check("VAD 모델", False, str(exc)))

    if translate:
        from .translate import TranslatorUnavailable, make_translator
        try:
            translator = make_translator(translate_model)
            checks.append(Check("Ollama 서버", True, f"{translator.host}"
                               if hasattr(translator, "host") else ""))
            try:
                available = translator.available_models()
                target = translate_model or translator.model
                has = any(target == m or m.startswith(target + ":") for m in available)
                checks.append(Check(f"번역 모델({target})", has,
                                   "" if has else f"안 받아져 있습니다: ollama pull {target}"))
            except Exception as exc:
                checks.append(Check("번역 모델 목록", False, str(exc)))
        except TranslatorUnavailable as exc:
            checks.append(Check("Ollama 서버", False, str(exc)))

    if diarize:
        from .diarize import DiarizationUnavailable, _find_diarize_python, _find_token
        try:
            py = _find_diarize_python()
            checks.append(Check("화자 분리 격리 환경(.venv-diarize)", True, str(py)))
        except DiarizationUnavailable as exc:
            checks.append(Check("화자 분리 격리 환경(.venv-diarize)", False, str(exc)))
        token = _find_token()
        checks.append(Check("Hugging Face 토큰", bool(token),
                           "" if token else "HF_TOKEN 환경변수가 없습니다"))

    try:
        anchor = video.resolve().anchor if video.is_file() else Path(".").resolve().anchor
        free_gb = shutil.disk_usage(anchor).free / 1_000_000_000
        checks.append(Check("디스크 여유 공간", free_gb >= min_free_gb,
                           f"{free_gb:.1f}GB"
                           + ("" if free_gb >= min_free_gb
                              else f" — {min_free_gb:.0f}GB 미만입니다")))
    except OSError:
        pass

    return checks


def report(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        mark = "OK  " if c.ok else "실패"
        lines.append(f"  [{mark}] {c.name}" + (f" — {c.detail}" if c.detail else ""))
    failed = [c for c in checks if not c.ok]
    lines.append("")
    if failed:
        lines.append(f"{len(failed)}건 실패 — 이대로 실행하면 중간에 멈출 가능성이 높습니다.")
    else:
        lines.append("환경 점검 통과했습니다. 이건 환경·의존성만 본 것입니다 — "
                     "번역 품질·TC 로직은 실행해 봐야 압니다.")
    return "\n".join(lines)
