"""화면 캡션 OCR 워커 — **격리 venv(`.venv-ocr`)에서만 돈다.**

`ocr.py`가 이 파일을 서브프로세스로 부른다. 직접 import해서 쓰지 않는다 —
EasyOCR이 시스템 파이썬의 torch와 다른 버전을 요구할 수 있다(`_diarize_worker.py`
와 같은 이유). 그래서 이 파일은 `checker` 패키지에 기대지 않고 표준 라이브러리 +
easyocr만 쓴다 — 격리 venv에는 PyYAML 같은 `checker`의 다른 의존성이 없다.

사용법: `python _ocr_worker.py <프레임목록.json> <출력.json> <언어>`
입력 프레임 목록: `[[시각ms, "프레임경로.png"], ...]`
출력: `[[시각ms, "텍스트", 신뢰도], ...]` — **글자를 못 찾은 프레임도 낸다**
(텍스트 `""`, 신뢰도 0.0). 처음엔 빼고 냈는데, `checker/ocr.py`의 TC 경계
정밀화가 "이 프레임엔 이 캡션이 없다"를 알아야 하는데 프레임 자체가 통째로
빠지면 그 정보가 사라진다(실사용 지적, 2026-08-31 — 정밀화가 경계를 거의
못 찾고 굵은 값 그대로 나옴). `merge_frames()`는 어차피 빈 텍스트를 걸러내니
(`checker/ocr.py`의 `kept = [... if conf >= min_confidence and text.strip()]`)
1단계 코드는 그대로 안전하다.
성공하면 0, 실패하면 표준에러에 이유를 적고 0이 아닌 값으로 끝난다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# `_diarize_worker.py`와 같은 이유로 자기 폴더를 sys.path에서 뺀다 — 이 파일이
# `checker/` 안에 있어 스크립트로 실행하면 `checker/profile.py`가 표준 라이브러리
# `profile` 모듈을 가려서 torch 내부의 `import profile`이 엉뚱한 모듈을 가져온다.
_own_dir = str(Path(__file__).resolve().parent)
if _own_dir in sys.path:
    sys.path.remove(_own_dir)

import json


def main() -> int:
    if len(sys.argv) < 4:
        print("사용법: _ocr_worker.py <프레임목록.json> <출력.json> <언어>",
              file=sys.stderr)
        return 2
    manifest_path = Path(sys.argv[1])
    out_json = Path(sys.argv[2])
    lang = sys.argv[3]

    try:
        import easyocr
    except ImportError as exc:
        print(f"easyocr이 설치돼 있지 않습니다: {exc}", file=sys.stderr)
        return 2

    frames = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not frames:
        out_json.write_text("[]", encoding="utf-8")
        return 0

    try:
        reader = easyocr.Reader([lang], gpu=False)
    except Exception as exc:
        print(f"OCR 모델을 불러오지 못했습니다: {exc}", file=sys.stderr)
        return 2

    results = []
    for ms, frame_path in frames:
        detections = reader.readtext(frame_path)
        if not detections:
            results.append([int(ms), "", 0.0])
            continue
        texts = [d[1] for d in detections]
        confs = [float(d[2]) for d in detections]
        results.append([int(ms), "\n".join(texts), sum(confs) / len(confs)])

    out_json.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
