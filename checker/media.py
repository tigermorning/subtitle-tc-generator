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


def _drive_of(path: Path) -> str:
    """WSL에서 이 경로가 어느 Windows 드라이브에 있는지(`/mnt/c` 꼴)."""
    parts = path.parts
    return "/".join(parts[:3]) if len(parts) >= 3 and parts[1] == "mnt" else ""


def _as_tool_path(path) -> str:
    """도구에 넘길 수 있는 경로로 바꾼다.

    **WSL에서 Windows 쪽 ffmpeg을 부를 때 `/mnt/c/...`는 통하지 않는다.** 그 경로는
    Windows에 존재하지 않는 이름이라 "Illegal byte sequence"나 "No such file"로
    죽는다(2026-08-11 실측). 한글이 섞이면 더 빨리 죽는다.

    작업 폴더 기준 **상대 경로**로 바꾸면 통한다 — WSL이 작업 폴더를 옮겨 주기
    때문이다. 드라이브가 달라 상대 경로를 만들 수 없으면 원래 경로를 그대로 넘긴다
    (그 경우는 부르는 쪽이 파일을 옮겨야 한다).
    """
    path = Path(path)
    if os.name == "nt" or not str(path).startswith("/mnt/"):
        return str(path)
    # **드라이브가 같아야 상대 경로가 뜻을 가진다.** 다르면 `../../../../d/...`처럼
    # /mnt 위로 올라갔다 내려오는 경로가 나오는데 Windows는 그것을 못 푼다.
    # 문자열 모양으로 걸러 보려다 두 번 틀렸다(작업 폴더 깊이에 따라 모양이 바뀐다).
    # 드라이브 자체를 견주는 것이 맞다.
    if _drive_of(path.resolve()) != _drive_of(Path.cwd()):
        return str(path)
    try:
        return os.path.relpath(path.resolve(), Path.cwd())
    except ValueError:
        return str(path)


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
         "-of", "default=noprint_wrappers=1", _as_tool_path(video)],
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


def detect_speech(video: Path, noise_db: int = -20, min_silence_s: float = 0.25,
                  duration_ms: int | None = None) -> list[tuple[int, int]]:
    """말소리 구간 [(시작ms, 끝ms)]. 조용한 구간을 찾아 그 사이를 말소리로 본다.

    **기준값은 전문가 타임코드와 대조해 골랐다**(2026-08-11, 6분 30초 영어 영상).
    -30dB에서 -20dB로 올리니 인점이 제자리를 찾았다 — 낮은 기준은 숨소리·잡음까지
    말소리로 보아 자막이 일찍 시작한다.

        -30dB   인점 중앙 -147ms, 100ms 안 21개
        -20dB   인점 중앙   +6ms, 100ms 안 28개   <- 이 값
        -40dB   인점 중앙 -257ms, 100ms 안 13개

    대신 말 끝의 잦아드는 소리를 일찍 자른다. 그 보정은 `timing.SPEECH_TAIL_FRAMES`가
    맡는다(둘을 같이 봐야 한다).


    음량 기준이라 배경 음악이나 효과음이 크면 경계가 흐려진다. 그때는 VAD 모델을
    붙여야 한다 — 여기서는 붙이지 않는다. **정확하지 않을 수 있는 값을 정답처럼
    쓰지 않기 위해**, 이 값은 자동 교정이 아니라 제안에만 쓴다.
    """
    out = subprocess.run(
        [_find("ffmpeg"), "-hide_banner", "-nostats", "-i", _as_tool_path(video),
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


def find_speech(video: Path, method: str = "auto", duration_ms: int | None = None,
                progress=None) -> tuple[list[tuple[int, int]], str]:
    """말소리 구간을 찾는다. (구간, 쓴 방법)

    **기본은 모델(VAD)이다.** 전문가·연습 자료 4편으로 견줬을 때(2026-08-11):

        자료                음량 -20dB          Silero VAD
        다큐(음악 깔림)      ±820ms, 31개        ±147ms, 66개
        다큐                구간 3개(실패)       ±499ms, 66개
        시트콤              ±411ms, 132개       ±422ms, 103개
        드라마(정답 파일)    ±255ms,  28개       ±352ms,  21개

    깨끗한 대사에서는 음량이 조금 낫고, 음악·잡음이 섞이면 VAD가 압도한다.
    **VAD를 기본으로 두는 이유는 최악을 없애기 때문이다** — 음량 검출은 어떤
    자료에서 30분짜리를 구간 3개로 잡았다. 그런 실패는 자막을 통째로 망친다.
    조금 손해 보더라도 무너지지 않는 쪽을 기본으로 한다.

    모델이나 onnxruntime이 없으면 조용히 음량으로 돌아간다.
    """
    say = progress or (lambda _m: None)
    if method in ("auto", "vad"):
        try:
            from .vad import detect_speech as vad_speech
            spans = vad_speech(video, progress=say)
            if spans:
                return spans, "vad"
            say("모델이 말소리를 찾지 못했습니다. 음량으로 다시 봅니다.")
        except Exception as exc:      # 모델·실행기가 없거나 도중에 실패
            if method == "vad":
                raise
            say(f"말소리 모델을 쓰지 못해 음량으로 찾습니다: {exc}")
    return detect_speech(video, duration_ms=duration_ms), "loudness"


SCENE_TIME = re.compile(r"pts_time:([\d.]+)")


def detect_shot_changes(video: Path, sensitivity: float = 0.2) -> list[int]:
    """장면 전환 시각(ms) 목록.

    민감도는 작업자 자료의 기본값(0.2)을 따른다. 낮을수록 예민하게 잡아서 배우가
    팔을 올리는 것도 전환으로 보고, 애니메이션은 오히려 높여야 한다고 적혀 있다.
    SubtitleEdit의 장면 전환 검출도 같은 ffmpeg 필터를 쓴다.
    """
    out = subprocess.run(
        [_find("ffmpeg"), "-hide_banner", "-nostats", "-i", _as_tool_path(video),
         "-vf", f"select='gt(scene,{sensitivity})',showinfo",
         "-f", "null", "-"],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace",
    )
    times = [int(float(m.group(1)) * 1000) for m in SCENE_TIME.finditer(out.stderr)]
    return sorted(set(times))


META_TIME = re.compile(r"pts_time:([\d.]+)")
META_VALUE = re.compile(r"lavfi\.signalstats\.YAVG=([\d.]+)")


def detect_bottom_text(video: Path, sample_fps: float = 2.0,
                       band: float = 0.25, sensitivity: float = 2.5,
                       ) -> list[tuple[int, int]]:
    """화면 **아래쪽에 글자가 타 있는** 것으로 보이는 구간 [(시작ms, 끝ms)].

    글자는 윤곽선이 많다. 화면 아래 4분의 1을 잘라 윤곽선만 남기고 밝기 평균을
    재면, 글자가 뜬 구간이 평소보다 뚜렷하게 튄다. 한 번의 ffmpeg 통과로 끝난다.

    **글자를 읽지 않는다. 글자인지도 확신하지 않는다.** 벽돌 무늬나 나뭇가지도
    윤곽선이 많다. 그래서 이 결과는 제안에만 쓰고 자동 교정에는 쓰지 않는다
    (`position.apply_positions`가 `certain=False`를 건너뛴다).

    기준은 중앙값에서 얼마나 떨어졌는지로 잡는다. 평균과 표준편차를 쓰면 밝은
    장면 몇 개에 기준이 끌려간다.
    """
    out = subprocess.run(
        [_find("ffmpeg"), "-hide_banner", "-nostats", "-i", _as_tool_path(video),
         "-vf", (f"fps={sample_fps},scale=320:-2,"
                 f"crop=iw:ih*{band}:0:ih*{1 - band},"
                 "edgedetect=low=0.1:high=0.3,signalstats,"
                 "metadata=print:key=lavfi.signalstats.YAVG"),
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace",
    )

    samples: list[tuple[float, float]] = []
    when: float | None = None
    for line in (out.stderr or "").splitlines():
        found = META_TIME.search(line)
        if found:
            when = float(found.group(1))
            continue
        found = META_VALUE.search(line)
        if found and when is not None:
            samples.append((when, float(found.group(1))))
            when = None
    if len(samples) < 4:
        return []

    values = sorted(v for _t, v in samples)
    middle = values[len(values) // 2]
    deviations = sorted(abs(v - middle) for v in values)
    spread = deviations[len(deviations) // 2] or 1.0
    threshold = middle + sensitivity * spread

    step_ms = int(1000 / sample_fps)
    spans: list[tuple[int, int]] = []
    for time_s, value in samples:
        if value < threshold:
            continue
        start = int(time_s * 1000)
        if spans and start - spans[-1][1] <= step_ms:
            spans[-1] = (spans[-1][0], start + step_ms)
        else:
            spans.append((start, start + step_ms))
    return spans


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
