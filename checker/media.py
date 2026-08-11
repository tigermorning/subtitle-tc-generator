"""영상에서 사실을 읽어 온다 — 프레임레이트, 길이, 말소리 구간.

**API를 쓰지 않는다.** 미공개 콘텐츠를 외부로 보내지 않는 것이 이 도구의 전제이고,
필요한 것은 전부 로컬 ffmpeg으로 된다. SubtitleEdit도 같은 것을 쓴다(파형 생성·장면
전환 검출이 내부적으로 ffmpeg이다).

ffmpeg을 못 찾으면 **조용히 넘어가지 않고** 없다고 알린다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaToolUnavailable(Exception):
    """ffmpeg/ffprobe를 찾지 못했다."""


def _windows_users() -> list[Path]:
    """WSL에서 본 Windows 사용자 폴더들. 리눅스 계정 이름과 다를 수 있다."""
    users = Path("/mnt/c/Users")
    if not users.is_dir():
        return []
    try:
        return [u for u in users.iterdir() if u.is_dir()]
    except OSError:
        return []


def _known_places(name: str):
    """도구가 흔히 놓이는 자리. Windows에서도 WSL에서도 같은 자리를 본다."""
    places = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        places.append(Path(appdata) / "Subtitle Edit" / "ffmpeg")
    home = Path.home()
    # winget으로 받은 것을 먼저 본다. Subtitle Edit이 딸려 보내는 ffmpeg은 8.0이라
    # whisper 필터가 없다 — 있는 쪽을 먼저 집어야 전사가 된다.
    places += [
        home / "AppData/Local/Microsoft/WinGet/Links",
        Path("/mnt/c/Program Files/ffmpeg/bin"),
        home / "AppData/Roaming/Subtitle Edit/ffmpeg",
    ]
    # winget은 실행 파일을 Links가 아니라 Packages 밑에 풀어 놓고 PATH에만 넣는다.
    # WSL에서 부르면 그 PATH가 없으므로 직접 찾아 준다.
    for root in {home / "AppData/Local/Microsoft/WinGet/Packages"} | {
            u / "AppData/Local/Microsoft/WinGet/Packages" for u in _windows_users()}:
        if root.is_dir():
            places += sorted(root.glob("Gyan.FFmpeg*/ffmpeg-*/bin"), reverse=True)

    # WSL에서 Windows 쪽 사용자 폴더를 볼 때는 리눅스 계정 이름이 다를 수 있다.
    places += [u / "AppData/Roaming/Subtitle Edit/ffmpeg" for u in _windows_users()]
    return [folder / f"{name}{suffix}" for folder in places for suffix in (".exe", "")]


def _find(name: str) -> str:
    """환경변수 > PATH > 흔한 자리 순으로 찾는다."""
    env = os.environ.get(f"{name.upper()}_PATH") or os.environ.get("FFMPEG_DIR")
    if env:
        candidate = Path(env)
        candidate = candidate / name if candidate.is_dir() else candidate
        for path in (candidate, candidate.with_suffix(".exe")):
            if path.is_file():
                return str(path)

    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if found:
        return found

    # **Subtitle Edit이 자기 ffmpeg을 가지고 있다.** SE 안에서 플러그인으로 돌 때
    # PATH가 비어 있어도 그것을 쓰면 된다 — 사용자에게 ffmpeg을 따로 깔라고 하지
    # 않아도 되고, SE가 쓰는 것과 같은 것을 써서 결과가 어긋나지 않는다.
    for candidate in _known_places(name):
        if candidate.is_file():
            return str(candidate)

    raise MediaToolUnavailable(
        f"{name}을(를) 찾지 못했습니다. PATH에 넣거나 {name.upper()}_PATH 환경변수로 "
        "경로를 지정하세요. 영상이 필요 없는 검사는 그대로 돌아갑니다."
    )


@dataclass
class MediaInfo:
    fps: float
    duration_ms: int
    width: int = 0
    height: int = 0
    variable_frame_rate: bool = False   # 화면 녹화물 등은 프레임레이트가 일정하지 않다

    @property
    def frame_ms(self) -> float:
        return 1000.0 / self.fps if self.fps else 0.0


def _ratio(text: str) -> float:
    if not text or "/" not in text:
        return float(text or 0)
    num, den = text.split("/", 1)
    return float(num) / float(den) if float(den) else 0.0


def probe(video: Path) -> MediaInfo:
    """프레임레이트와 길이를 읽는다. 프레임 단위 규정을 밀리초로 옮길 때 쓴다."""
    out = subprocess.run(
        [_find("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate,avg_frame_rate,width,height",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1", str(video)],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise MediaToolUnavailable(f"영상을 읽지 못했습니다: {out.stderr.strip()[:200]}")

    values = dict(
        line.split("=", 1) for line in out.stdout.splitlines() if "=" in line
    )
    rate = _ratio(values.get("r_frame_rate", "0"))
    average = _ratio(values.get("avg_frame_rate", "0"))
    # 화면 녹화물은 r_frame_rate가 60인데 실제 평균은 29 같은 식으로 벌어진다.
    # 타임코드 규정은 표시 프레임레이트를 따르므로 r_frame_rate를 쓰되 사실을 알린다.
    vfr = bool(rate and average and abs(rate - average) / rate > 0.05)
    return MediaInfo(
        fps=rate or average or 23.976,
        duration_ms=int(float(values.get("duration", 0) or 0) * 1000),
        width=int(values.get("width", 0) or 0),
        height=int(values.get("height", 0) or 0),
        variable_frame_rate=vfr,
    )


SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_speech(video: Path, noise_db: int = -30, min_silence_s: float = 0.25,
                  duration_ms: int | None = None) -> list[tuple[int, int]]:
    """말소리 구간 [(시작ms, 끝ms)]. 조용한 구간을 찾아 그 사이를 말소리로 본다.

    음량 기준이라 배경 음악이나 효과음이 크면 경계가 흐려진다. 그때는 VAD 모델을
    붙여야 한다 — 여기서는 붙이지 않는다. **정확하지 않을 수 있는 값을 정답처럼
    쓰지 않기 위해**, 이 값은 자동 교정이 아니라 제안에만 쓴다.
    """
    out = subprocess.run(
        [_find("ffmpeg"), "-hide_banner", "-nostats", "-i", str(video),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_s}",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace",
    )
    log = out.stderr

    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in log.splitlines():
        m = SILENCE_START.search(line)
        if m:
            start = float(m.group(1))
            continue
        m = SILENCE_END.search(line)
        if m and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:
        silences.append((start, float("inf")))

    total = duration_ms if duration_ms is not None else 0
    speech: list[tuple[int, int]] = []
    cursor = 0.0
    for s_start, s_end in silences:
        if s_start > cursor:
            speech.append((int(cursor * 1000), int(s_start * 1000)))
        cursor = s_end if s_end != float("inf") else cursor
    if total and cursor * 1000 < total:
        speech.append((int(cursor * 1000), total))
    return [(a, b) for a, b in speech if b > a]


SCENE_TIME = re.compile(r"pts_time:([\d.]+)")


def detect_shot_changes(video: Path, sensitivity: float = 0.2) -> list[int]:
    """장면 전환 시각(ms) 목록.

    민감도는 작업자 자료의 기본값(0.2)을 따른다. 낮을수록 예민하게 잡아서 배우가
    팔을 올리는 것도 전환으로 보고, 애니메이션은 오히려 높여야 한다고 적혀 있다.
    SubtitleEdit의 장면 전환 검출도 같은 ffmpeg 필터를 쓴다.
    """
    out = subprocess.run(
        [_find("ffmpeg"), "-hide_banner", "-nostats", "-i", str(video),
         "-vf", f"select='gt(scene,{sensitivity})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace",
    )
    times = [int(float(m.group(1)) * 1000) for m in SCENE_TIME.finditer(out.stderr)]
    return sorted(set(times))


VIDEO_SUFFIXES = (".mkv", ".mp4", ".mov", ".avi", ".m4v", ".ts", ".wmv", ".webm")


def find_video_for(subtitle: Path) -> Path | None:
    """자막 옆에서 같은 이름의 영상을 찾는다.

    실무에서 영상과 자막은 한 폴더에 같은 이름으로 있다(`ep01.mkv` / `ep01.srt`).
    경로를 손으로 넣게 하면 끌어다 놓기 방식에서 못 쓴다.

    `.fixed.srt` 같은 꼬리표가 붙어 있으면 떼고 찾는다.
    """
    stem = subtitle.stem
    for tag in (".fixed", "_ko_TL", "_TL"):
        if stem.endswith(tag):
            stem = stem[: -len(tag)]
    for suffix in VIDEO_SUFFIXES:
        for name in (subtitle.stem, stem):
            candidate = subtitle.with_name(name + suffix)
            if candidate.is_file():
                return candidate
    return None
