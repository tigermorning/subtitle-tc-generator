"""사용자 설정 — 규정이 아니라 **취향**에 속하는 것들.

작업 기준(규정)은 프로파일에 있고, 여기 있는 것은 사람마다 다른 선택이다.
자막이 규정을 어겼는지와 무관하므로 섞지 않는다.

    프로파일    한 줄 16자, 최소 0.834초    발주처가 정한다
    설정        저장할 때 원어도 낼지        사람이 정한다

`%APPDATA%\\자막생성기\\settings.json`에 남는다. **바꾼 것만 적는다** — 기본값이
나중에 바뀌면 따라가야 한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from checker.translate import DEFAULT_MODEL, OPEN_LICENCE_MODEL

DEFAULTS = {
    # 저장
    "save_source_too": True,        # 원어 자막도 함께 낸다
    "save_suffix": ".edited",       # 원본을 덮지 않도록 붙이는 꼬리표
    # 파형
    "waveform_ms_per_pixel": 20,
    "waveform_show_speech": True,   # 말소리 구간 띠
    "waveform_show_shots": True,    # 장면 전환 선
    "waveform_follow": True,        # 재생 위치를 따라간다
    # 만들기
    "speech_method": "auto",        # auto | vad | loudness
    "whisper_language": "en",
    "translate_passes": 3,
    "use_knp": True,
    "web_terms": True,              # 용어를 밖에서도 찾는다(낱말만 나간다)
    # 도구 자리 — 비우면 스스로 찾는다
    "ffmpeg_path": "",
    "whisper_model": "",
    "translate_model": DEFAULT_MODEL,
    "corrector_path": "",
}


@dataclass(frozen=True)
class Option:
    key: str
    title: str
    what: str           # **무엇을 하는 설정인지.** 모르면 건드리지 못한다
    group: str
    kind: str = "bool"  # bool | int | text | choice
    choices: tuple = ()


OPTIONS = (
    Option("save_source_too", "원어 자막도 함께 저장", "번역본을 저장할 때 원어를 "
           "`<이름>.원어.srt`로 함께 낸다. 검수자가 원어를 본다.", "저장"),
    Option("save_suffix", "저장할 때 붙이는 꼬리표", "원본을 덮어쓰지 않으려고 이름 뒤에 "
           "붙인다. 자동 교정이 틀렸을 때 원본이 없으면 되돌릴 수 없다.", "저장", "text"),
    Option("waveform_ms_per_pixel", "파형 기본 확대(ms/픽셀)", "낮을수록 크게 보인다. "
           "20이면 화면 하나에 약 20초가 들어온다.", "파형", "int"),
    Option("waveform_show_speech", "말소리 구간 표시", "모델이 찾은 말소리를 옅은 띠로 "
           "깐다. 인점을 어디로 잡을지 견주는 기준이 된다.", "파형"),
    Option("waveform_show_shots", "장면 전환 표시", "장면이 바뀌는 자리를 세로선으로 "
           "그린다. 자막이 그 선에 걸치면 안 된다.", "파형"),
    Option("waveform_follow", "재생 위치 따라가기", "재생하면 파형이 저절로 흐른다. "
           "끄면 보던 자리에 머문다.", "파형"),
    Option("speech_method", "말소리 찾는 방법", "auto는 모델(VAD)을 먼저 쓰고 없으면 "
           "음량으로 돌아간다. 음악이 깔린 다큐에서는 모델이 훨씬 낫다.", "만들기",
           "choice", ("auto", "vad", "loudness")),
    Option("whisper_language", "원어", "전사할 말의 언어. 아는 값을 주면 정확해진다.",
           "만들기", "choice", ("en", "ko", "ja", "zh", "auto")),
    Option("translate_passes", "번역 차수", "1차는 빠른 초벌, 2차는 용어와 맥락, "
           "3차는 말맛. 작업자가 하는 순서와 같다.", "만들기", "int"),
    Option("use_knp", "KNP 시트 자동으로 쓰기", "자막 옆에 KNP 파일이 있으면 읽어 용어를 "
           "고정한다. 이미 있는 것을 다시 만들게 하지 않는다.", "만들기"),
    Option("web_terms", "용어를 밖에서도 찾기", "규범 용례에 없는 용어를 위키백과에서 "
           "찾는다. **낱말만 나간다** — 대사는 나가지 않는다.", "만들기"),
    Option("ffmpeg_path", "ffmpeg 자리", "비우면 스스로 찾는다. 전사에는 9.0 이상이 "
           "필요하다.", "도구", "text"),
    Option("whisper_model", "전사 모델 파일", "비우면 사용자 자료 폴더의 models에서 "
           "가장 큰 것을 쓴다.", "도구", "text"),
    Option("translate_model", "번역 모델", "Ollama에 받아 둔 이름. exaone3.5가 한국어에 "
           "낫지만(실측) 상업 이용에 제약이 있는 라이선스다. "
           "{OPEN_LICENCE_MODEL}은 Apache 2.0.".replace(
               "{OPEN_LICENCE_MODEL}", OPEN_LICENCE_MODEL), "도구", "text"),
    Option("corrector_path", "한국어 교정기 자리", "비우면 편집기 폴더 옆에서 찾는다.",
           "도구", "text"),
)

GROUPS = ("저장", "파형", "만들기", "도구")


def _path():
    from checker.paths import user_data

    folder = user_data()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


def load() -> dict:
    values = dict(DEFAULTS)
    path = _path()
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return values
        for key, value in saved.items():
            if key in values and type(value) is type(values[key]):
                values[key] = value
    return values


def save(values: dict) -> None:
    """바꾼 것만 남긴다."""
    changed = {key: values[key] for key in DEFAULTS
               if key in values and values[key] != DEFAULTS[key]}
    _path().write_text(json.dumps(changed, ensure_ascii=False, indent=2),
                       encoding="utf-8")
