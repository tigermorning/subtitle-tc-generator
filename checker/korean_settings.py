"""한국어 교정 설정 — 교정기 웹앱 «2단계 · 교정 옵션»을 편집기 안으로 옮긴 것.

**왜 있나.** 편집기는 교정기(`korean-subtitle-corrector`)를 라이브러리로 빌려 쓰는데,
웹앱에서 고를 수 있는 옵션(구두점 표기·자막 편집 표지·띄어쓰기 기준·고유명사·사투리)을
넘길 길이 없었다. 그래서 작업자가 같은 교정을 받으려면 웹앱을 따로 열어야 했다.

**이름·기본값은 웹앱(`static/index.html`)과 같다.** 하나만 다르다 — `사용 목적`의
웹앱 기본값은 `일반 글`이지만 편집기가 다루는 것은 언제나 자막이라 `자막`이 기본이다
(지금까지 편집기가 늘 `doc_type="subtitle"`로 불렀으므로 결과도 바뀌지 않는다).

**발주처 프로파일이 정한 것은 기본값으로 채운다**(화자명·어조 부호, 말줄임표). 사용자가
바꾸면 그 값만 따로 저장한다(`overrides`). 그래서 저장해 둔 작품의 발주처를 나중에
바꿔도, 사용자가 손대지 않은 칸은 새 발주처 기본값을 따른다.

**작품 단위로 저장한다.** 자막 옆 작업 폴더(`<자막이름>.work/`, `checker/work.py`)의
`korean-settings.json`. 교정기 쪽 함수는 여기서 부르지 않는다 — 이 모듈은 교정기
없이도 돈다(시험·설정 창).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path

from .profile import speaker_enclosure

FILE_NAME = "korean-settings.json"

# 웹앱 선택지와 표시 문구. (값, 화면 문구) — 순서가 화면 순서다.
DOC_TYPES = (("subtitle", "자막"), ("prose", "일반 글"))
ELLIPSIS_STYLES = (("keep", "원문 유지 (권장)"), ("dots", "온점 세 개 (...)"),
                   ("char", "한 글자 (…)"))
QUOTE_STYLES = (("keep", "원문 유지 (권장)"), ("half", "곧은따옴표 ( ' \" )"),
                ("full", "둥근따옴표 ( ‘ ’ “ ” )"))
SPACING_MODES = (("principle", "원칙 — 띄어 씀"), ("allowance", "허용 — 붙여 씀"))
DIALECT_MODES = (("protect", "그대로 보호 (교정·플래그 안 함)"),
                 ("assist", "사투리로 고쳐주기 제안"),
                 ("to_standard", "표준어로 바꾸기 제안 (자동 변환 아님)"))

_CHOICES = {
    "doc_type": DOC_TYPES, "ellipsis": ELLIPSIS_STYLES, "quotes": QUOTE_STYLES,
    "spacing_mode": SPACING_MODES, "dialect_mode": DIALECT_MODES,
}


@dataclass
class KoreanSettings:
    """한 작품의 한국어 교정 설정. 기본값 = 웹앱 기본값(사용 목적만 `자막`)."""

    doc_type: str = "subtitle"
    ellipsis: str = "keep"
    quotes: str = "keep"
    screen_text_marker: str = ""
    line_break_marker: str = ""
    position_marker: str = ""
    speaker_bracket: str = ""      # 비우면 교정기가 대괄호로 본다
    tone_bracket: str = ""
    spacing_mode: str = "principle"
    names: list[str] = field(default_factory=list)
    dialect_region: str = ""       # 문서 전체. 비우면 «설정 안함»
    dialect_mode: str = "protect"
    # 화자별: {화자 이름: {"region": 지역 또는 "", "mode": 모드}}
    speaker_dialects: dict[str, dict[str, str]] = field(default_factory=dict)

    # ------------------------------------------------------------ 직렬화
    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict | None) -> "KoreanSettings":
        """모르는 키는 버리고, 모르는 선택값은 기본값으로 떨어뜨린다(웹앱 정규화와 같다)."""
        out = cls()
        for key, value in (data or {}).items():
            if not hasattr(out, key):
                continue
            setattr(out, key, value)
        return out.normalized()

    def normalized(self) -> "KoreanSettings":
        default = KoreanSettings()
        for key, choices in _CHOICES.items():
            if getattr(self, key) not in {v for v, _ in choices}:
                setattr(self, key, getattr(default, key))
        for key in ("screen_text_marker", "line_break_marker", "position_marker",
                    "speaker_bracket", "tone_bracket", "dialect_region"):
            setattr(self, key, str(getattr(self, key) or "").strip())
        self.names = parse_names(self.names)
        clean: dict[str, dict[str, str]] = {}
        for speaker, spec in (self.speaker_dialects or {}).items():
            speaker = str(speaker).strip()
            if not speaker or not isinstance(spec, dict):
                continue
            mode = spec.get("mode") if spec.get("mode") in {v for v, _ in DIALECT_MODES} \
                else "protect"
            clean[speaker] = {"region": str(spec.get("region") or "").strip(), "mode": mode}
        self.speaker_dialects = clean
        return self

    # ------------------------------------------------------------ 교정기에 넘길 값
    def dialect_map(self) -> dict[str, str]:
        """웹앱 `getDialectMap()`과 같다 — 지역을 고른 화자만."""
        return {s: d["region"] for s, d in self.speaker_dialects.items() if d["region"]}

    def dialect_modes(self) -> dict[str, str]:
        """웹앱 `getDialectModes()`처럼 화자를 적은 줄은 지역이 비어도 모드를 넘긴다."""
        return {s: d["mode"] for s, d in self.speaker_dialects.items()}


def parse_names(value) -> list[str]:
    """«한 줄에 하나씩». 문자열이면 줄로 가르고, 빈 줄·중복은 버린다(순서 유지)."""
    if isinstance(value, str):
        value = value.splitlines()
    seen: list[str] = []
    for item in value or []:
        item = str(item).strip()
        if item and item not in seen:
            seen.append(item)
    return seen


def profile_defaults(profile: dict | None) -> KoreanSettings:
    """발주처 프로파일이 정해 주는 칸을 채운 기본 설정.

    `korean._corrector_options`가 해 오던 옮김과 같다: 화자명 부호, 어조 부호(없으면
    효과음 부호, 그것도 없으면 화자명 부호), 말줄임표 글자. 프로파일이 정하지 않은
    칸은 웹앱 기본값 그대로다.
    """
    base = KoreanSettings()
    if not profile:
        return base
    speaker = speaker_enclosure(profile)
    tone = ((profile.get("tone") or {}).get("enclosure")
            or (profile.get("sound_effect") or {}).get("enclosure")
            or speaker)
    base.speaker_bracket = speaker or ""
    base.tone_bracket = tone or ""
    ellipsis = {"…": "char", "...": "dots"}.get((profile.get("text") or {}).get("ellipsis_char"))
    if ellipsis:
        base.ellipsis = ellipsis
    return base


def effective(overrides: dict | None, profile: dict | None) -> KoreanSettings:
    """프로파일 기본값 위에 사용자가 바꾼 칸만 얹는다."""
    data = profile_defaults(profile).to_dict()
    data.update(overrides or {})
    return KoreanSettings.from_dict(data)


def diff_from_defaults(settings: KoreanSettings, profile: dict | None) -> dict:
    """저장할 것: 프로파일 기본값과 다른 칸만."""
    base = profile_defaults(profile).to_dict()
    now = settings.normalized().to_dict()
    return {k: v for k, v in now.items() if base.get(k) != v}


# ---------------------------------------------------------------- 작품 단위 저장

def settings_file(subtitle_path: Path | str) -> Path:
    from .work import Work
    return Work.beside(Path(subtitle_path)).root / FILE_NAME


def load_overrides(subtitle_path: Path | str | None) -> dict:
    """저장된 바꾼 칸. 없거나 깨졌으면 빈 값 — 설정이 깨졌다고 교정이 멈추면 안 된다."""
    if not subtitle_path:
        return {}
    path = settings_file(subtitle_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    overrides = data.get("overrides") if isinstance(data, dict) else None
    return overrides if isinstance(overrides, dict) else {}


def save_overrides(subtitle_path: Path | str, overrides: dict) -> Path:
    """작업 폴더에 쓴다. 원본 자막은 건드리지 않는다(작업 폴더 안에만 쓴다)."""
    path = settings_file(subtitle_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "overrides": overrides},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path
