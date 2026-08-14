"""무엇을 찾았고 무엇을 못 찾았는지 스스로 말한다.

**왜 필요한가**: 이 프로그램은 밖에 있는 것을 여럿 빌려 쓴다 — ffmpeg, whisper 모델,
Ollama, 한국어 교정기. 하나가 없으면 그 기능만 조용히 안 되는데, 사용자는 프로그램이
고장 났다고 여긴다. 실제로 그런 일이 있었다(교정기의 `.env`를 못 찾아 사전 조회가
통째로 죽었는데 오류처럼 보이지도 않았다).

그래서 **찾은 것과 못 찾은 것을 한 자리에 늘어놓는다.** 못 찾은 것에는 어디서 받는지
적는다.
"""

from __future__ import annotations

import os
from pathlib import Path


def _line(name: str, found, detail: str = "", how: str = "") -> dict:
    return {"name": name, "ok": bool(found),
            "detail": str(detail) if found else how}


def collect() -> list[dict]:
    """검사 결과 목록. 화면과 파일 양쪽에서 같은 것을 쓴다."""
    out: list[dict] = []

    from .log import log_path
    out.append(_line("기록(log)", True, str(log_path())))

    # --- 엔진 ---------------------------------------------------------
    try:
        from checker.profile import RULES_ROOT, available_profiles, user_root
        profiles = available_profiles()
        out.append(_line("규정 파일", RULES_ROOT.is_dir(),
                         f"{RULES_ROOT} — 기준 {len(profiles)}개"))
        out.append(_line("발주처 기준 자리", True, str(user_root())))
    except Exception as exc:
        out.append(_line("규정 파일", False, how=f"불러오지 못했습니다: {exc}"))

    # --- 영상 ---------------------------------------------------------
    try:
        from .runtime import find_libmpv
        found = find_libmpv()
        out.append(_line("영상 재생(libmpv)", found, found,
                         "bin 폴더에 libmpv-2.dll이 필요합니다"))
    except Exception as exc:
        out.append(_line("영상 재생(libmpv)", False, how=str(exc)))

    try:
        from checker.media import _find
        ffmpeg = _find("ffmpeg")
        out.append(_line("ffmpeg", True, ffmpeg))
    except Exception:
        out.append(_line("ffmpeg", False,
                         how="winget install Gyan.FFmpeg 로 설치하세요"))

    # --- 전사 ---------------------------------------------------------
    try:
        from checker.transcribe import ffmpeg_with_whisper
        out.append(_line("전사(whisper 필터)", True, ffmpeg_with_whisper()))
    except Exception as exc:
        out.append(_line("전사(whisper 필터)", False, how=str(exc).splitlines()[0]))

    try:
        from checker.transcribe import find_model
        model = find_model()
        size = model.stat().st_size / 1_000_000
        out.append(_line("전사 모델", True, f"{model.name} ({size:.0f}MB)"))
    except Exception as exc:
        out.append(_line("전사 모델", False, how=str(exc).splitlines()[0]))

    # --- 말소리 검출 ---------------------------------------------------
    try:
        from checker.vad import find_model as find_vad
        out.append(_line("말소리 모델(VAD)", True, find_vad().name))
    except Exception as exc:
        out.append(_line("말소리 모델(VAD)", False, how=str(exc).splitlines()[0]))

    # --- 번역 ---------------------------------------------------------
    try:
        from checker.translate import make_translator
        translator = make_translator()
        models = translator.available_models()
        out.append(_line("번역(로컬 모델)", bool(models),
                         ", ".join(models[:3]) or "모델 없음",
                         "ollama pull exaone3.5:7.8b"))
    except Exception as exc:
        out.append(_line("번역(로컬 모델)", False, how=str(exc).splitlines()[0]))

    # --- 한국어 교정기 --------------------------------------------------
    # **어느 판이 붙어 있고 계약이 맞는지까지 말한다.** 두 저장소가 라이브러리로
    # 물려 있어서, 교정기가 함수 모양을 바꾸면 이쪽이 깨진다. 그 사고는 실사용
    # 중에야 드러나므로 진단이 미리 짚어 준다(2026-08-14).
    try:
        from checker.korean import corrector_info
        info = corrector_info()
    except Exception as exc:
        info = {"found": False, "path": None, "commit": None,
                "contract": "no-corrector", "detail": str(exc).splitlines()[0]}

    out.append(_line("한국어 교정기", info["found"], info["path"],
                     "편집기 폴더 옆에 두거나 KSC_PATH로 알려 주세요"))
    if info["found"]:
        label = {"ok": "맞습니다", "broken": "어긋났습니다",
                 "unknown": "확인하지 못했습니다"}.get(info["contract"], info["contract"])
        how = info["detail"] if info["contract"] != "ok" else ""
        out.append(_line("교정기 계약", info["contract"] == "ok",
                         f"{label}{' · ' + info['commit'] if info['commit'] else ''}",
                         how or "교정기의 tools/check_public_api.py가 판정합니다"))
    return out


def as_text(rows: list[dict] | None = None) -> str:
    rows = rows or collect()
    lines = ["자막 및 TC 생성기 진단", ""]
    for row in rows:
        mark = "OK  " if row["ok"] else "없음"
        lines.append(f"  [{mark}] {row['name']:20} {row['detail']}")
    missing = [r["name"] for r in rows if not r["ok"]]
    lines.append("")
    lines.append("모두 갖춰졌습니다." if not missing
                 else "없는 것: " + ", ".join(missing)
                      + "\n(없는 기능만 안 됩니다. 나머지는 그대로 씁니다.)")
    return "\n".join(lines)
