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

**이어하기(resume, 2026-08-31)**: `--ocr-hardsub`는 71분 영상 기준 7~8시간짜리
스캔이다(`checker/ocr.py` 독스트링) — 절전·재부팅·강제 종료로 중간에 끊기면
처음부터 다시 도는 비용이 실전에서 못 버틸 수준이라는 게 코드 동작 분석으로
드러났다(재현은 못 함 — 몇 시간대 작업이라). 그래서 `out_json`을 **매 프레임
처리 뒤 바로 디스크에 쓴다**(끝에 한 번만 쓰지 않는다). 실행할 때 `out_json`이
이미 있으면(전에 끊긴 흔적) 거기 있는 시각(ms)은 다시 안 돌고 그대로 이어
쓴다. 쓰기는 임시 파일에 쓴 뒤 `os.replace()`로 바꿔치기한다(원자적 — 쓰다
죽어도 `out_json`은 항상 이전의 온전한 상태이거나 새 온전한 상태 둘 중
하나다, 반쯤 쓰인 깨진 JSON이 될 수 없다). **어느 체크포인트를 이어써도
되는지(같은 영상·같은 설정인지) 판단은 `checker/ocr.py`가 한다** — 설정이
달라졌으면 이 파일을 부르기 전에 지우고 부른다. 이 파일 자체는 "그 경로에
있는 값은 이미 처리된 것"이라고만 믿는다.
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
import os
import tempfile

# Windows 콘솔 기본 인코딩(cp949)에서 죽지 않게 한다 — `checker/cli.py`의
# `_fix_console_encoding()`과 같은 이유·같은 처방이지만, 이 파일은 **별도
# 프로세스**라 cli.py의 reconfigure가 여기까지 안 미친다. 실측(2026-08-31):
# EasyOCR이 첫 실행에서 모델을 내려받을 때 tqdm 진행바가 U+2588(전각 블록)을
# 찍는데, cp949로는 인코딩이 안 돼 다운로드 도중 `UnicodeEncodeError`로
# 워커가 죽는다 — 신뢰도 몇이 아니라 **모든 첫 실행이 100% 재현**됐다(영어
# 인식 모델이 `~/.EasyOCR/model/temp.zip`으로 멈춘 채 완성되지 않음).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _load_existing(out_json: Path) -> dict[int, list]:
    """이전에 끊긴 실행이 남긴 `out_json`을 읽는다. 없거나 깨졌으면 빈 채로 새로 시작한다."""
    if not out_json.is_file():
        return {}
    try:
        data = json.loads(out_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {int(ms): [str(text), float(conf)] for ms, text, conf in data}


def _save_atomic(out_json: Path, results: dict[int, list]) -> None:
    """`out_json`을 통째로 다시 쓴다 — 임시 파일 + `os.replace()`(원자적 교체).

    쓰다 죽어도 `out_json`은 항상 직전 온전한 상태이거나 새 온전한 상태다 —
    반쯤 쓰인 파일이 될 수 없다(`os.replace`는 같은 드라이브 안에서 원자적).
    """
    payload = [[ms, *results[ms]] for ms in sorted(results)]
    fd, tmp_name = tempfile.mkstemp(dir=str(out_json.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp_name, out_json)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


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

    # **이어하기(2026-08-31).** `out_json`에 이미 있는 시각(ms)은 전에 끊긴
    # 실행이 이미 처리한 것이다 — 다시 안 돌린다. 어느 체크포인트를 믿어도
    # 되는지(같은 영상·같은 설정인지)는 `checker/ocr.py`가 호출 전에 이미
    # 판단해서, 안 맞으면 지우고 부른다 — 여기서는 있으면 그냥 믿는다.
    results = _load_existing(out_json)
    resumed = len(results)
    if resumed:
        print(f"이전 실행 이어받음: {resumed}개 프레임은 다시 안 돕니다",
              file=sys.stderr)

    # **GPU를 쓴다(2026-09-09) — CPU 고정으로 실측 10시간 걸린 것을 보고 확인.**
    # `.venv-ocr`가 torch를 CPU판으로 설치받아 `gpu=False`가 박혀 있었다(이유를
    # 설명하는 주석이 없었다 — 격리 venv를 처음 만들 때 그냥 기본 pip 설치가
    # CPU판이었던 것으로 보인다). 이 컴퓨터엔 RTX 3060 Ti(8GB)가 있는데 안
    # 쓰고 있었다. `.venv-ocr`에 CUDA torch를 재설치한 뒤(`pip install torch
    # torchvision --index-url https://download.pytorch.org/whl/cu124`) `gpu=True`로
    # 바꿨다 — 같은 모델·같은 인식 알고리즘이라 정확도 손해는 없다.
    # **다른 환경(CUDA torch 없이 새로 설치한 경우)에서도 안전하다** — EasyOCR은
    # `torch.cuda.is_available()`이 거짓이면 `gpu=True`를 줘도 경고만 찍고 CPU로
    # 조용히 돌아간다(예외를 던지지 않는다, 직접 확인).
    try:
        reader = easyocr.Reader([lang], gpu=True)
    except Exception as exc:
        print(f"OCR 모델을 불러오지 못했습니다: {exc}", file=sys.stderr)
        return 2

    for ms, frame_path in frames:
        ms = int(ms)
        if ms in results:
            continue
        # **프레임 하나가 죽어도 나머지를 계속 돈다.** 실측(2026-08-31,
        # 손상된 프레임으로 재현): `readtext()`는 프레임을 못 읽으면(끊긴
        # ffmpeg 출력·0바이트 파일 등) 예외를 던진다(`OSError`) — 잡지
        # 않으면 이 함수는 결과를 마지막에 한 번에 `out_json`으로 쓰므로,
        # 프레임 하나가 루프 중간에 이 예외로 죽으면 그때까지 처리한 결과가
        # **전부** 사라진다(`out_json` 자체가 안 만들어져 부모 프로세스는
        # "실패"로만 본다). `--ocr-hardsub`처럼 몇 시간짜리 전체 회차 스캔
        # 중 프레임 한 장 때문에 처음부터 다시 도는 것을 막는다 — 이
        # 프레임은 "글자 없음"과 같은 값(빈 텍스트, 신뢰도 0)으로 남기고
        # 계속한다(`merge_frames()`가 어차피 이런 프레임은 걸러낸다).
        try:
            detections = reader.readtext(frame_path)
        except Exception as exc:
            print(f"프레임을 읽지 못해 건너뜁니다({frame_path}): {exc}",
                  file=sys.stderr)
            detections = []
        if not detections:
            results[ms] = ["", 0.0]
        else:
            texts = [d[1] for d in detections]
            confs = [float(d[2]) for d in detections]
            results[ms] = ["\n".join(texts), sum(confs) / len(confs)]
        # **매 프레임 뒤 바로 디스크에 남긴다.** 이 파일이 이어하기의 유일한
        # 근거라, 마지막까지 메모리에만 쌓았다가 끝에 한 번 쓰면(예전 방식)
        # 죽었을 때 잃는 게 똑같아진다.
        _save_atomic(out_json, results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
