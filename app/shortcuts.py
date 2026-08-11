"""무엇을 할 수 있는지, 어떤 키로 하는지.

**설명이 키보다 중요하다.** 사용자 지적(2026-08-12): 어떤 기능을 쓸 수 있는지 알아야
프로그램을 잘 쓴다. 단축키 목록만 늘어놓으면 "이게 무슨 일을 하는지" 모른 채 남는다.

그래서 기능마다 **왜 쓰는지**를 함께 적는다. 환경설정에서 이 설명을 그대로 보여 준다.

키는 **기본값일 뿐이다.** 손이 기억하는 자리는 사람마다 다르고, 다른 도구를 쓰다 온
사람은 그 도구의 자리가 편하다. 바꾼 값은 사용자 자료 폴더에 남아 프로그램을 다시
깔아도 유지된다.

기본값은 작업자가 SubtitleEdit에서 쓰던 자리를 그대로 옮긴 것이다(작업자 자료의
단축키 목록) — 손이 기억하는 자리를 바꾸면 그것만으로 도구를 못 쓴다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    key: str            # 기능 이름(설정 파일에 남는 이름)
    default: str        # 기본 단축키
    title: str          # 화면에 보이는 이름
    slot: str           # 창의 메서드 이름
    group: str          # 묶음
    what: str           # **무엇을 하는지, 왜 쓰는지**


ACTIONS = (
    Action("play", "Esc", "재생 / 일시정지", "toggle_play", "재생",
           "영상을 재생하거나 멈춘다. 자막 작업은 듣고 멈추기의 반복이라 가장 많이 쓴다."),
    Action("step_back", "Ctrl+Shift+Left", "1프레임 뒤로", "step_back", "재생",
           "한 프레임씩 되돌린다. 인점을 프레임 단위로 맞출 때 쓴다 — 한 프레임(약 42ms) "
           "어긋나면 검수에서 돌아온다."),
    Action("step_forward", "Ctrl+Shift+Right", "1프레임 앞으로", "step_forward", "재생",
           "한 프레임씩 나아간다. 말이 시작되는 정확한 프레임을 찾을 때 쓴다."),
    Action("previous", "PgUp", "이전 자막으로", "go_previous", "이동",
           "앞 자막을 고르고 영상도 그 자리로 옮긴다. 자막을 훑으며 확인할 때 쓴다."),
    Action("next", "PgDown", "다음 자막으로", "go_next", "이동",
           "다음 자막을 고르고 영상도 그 자리로 옮긴다."),
    Action("go_number", "Ctrl+G", "자막 번호로 이동", "go_to_number", "이동",
           "번호를 입력해 그 자막으로 간다. 검수 지적이 번호로 오기 때문에 필요하다."),
    Action("split", "Ctrl+Space", "재생 위치에서 나누기", "split_cue", "편집",
           "지금 보고 있는 자리에서 자막을 둘로 나눈다. 스포팅에서 가장 많이 쓰는 조작이다 "
           "— 글자는 시간 비율로 나뉘고, 다듬는 것은 그다음 일이다."),
    Action("merge", "Alt+Space", "다음 자막과 합치기", "merge_cue", "편집",
           "한 사람의 말이 두 자막으로 끊겨 있을 때 합친다(독백). 줄만 바뀐다."),
    Action("merge_dialogue", "Alt+Shift+Space", "대화로 합치기", "merge_dialogue", "편집",
           "두 사람이 주고받는 말을 한 자막에 담는다. 앞에 하이픈을 붙여 화자를 가른다."),
    Action("dash", "Ctrl+-", "대화 하이픈 넣고 빼기", "toggle_dash", "편집",
           "줄 앞의 `- `를 붙였다 뗀다. 두 사람 대화 표기다."),
    Action("unbreak", "Ctrl+\\", "줄바꿈 제거", "remove_breaks", "편집",
           "두 줄을 한 줄로 붙인다. 줄바꿈 자리를 다시 잡을 때 한 번에 풀고 시작한다."),
    Action("top", "Alt+Up", "자막을 위로", "place_top", "위치",
           "화면 위(상단 중앙, {\\an8})로 올린다. 화면 아래에 글자가 있어 겹칠 때 쓴다."),
    Action("bottom", "Alt+Down", "자막을 아래로", "place_bottom", "위치",
           "기본 자리(화면 아래)로 되돌린다. 겹침이 끝났는데 올린 채로 두면 그 뒤 자막이 "
           "계속 위에 뜬다."),
    Action("in_point", "F5", "인점을 지금 위치로", "set_in_point", "타임코드",
           "재생 위치를 이 자막의 시작으로 삼는다. 이웃 자막을 침범하면 하지 않는다."),
    Action("out_point", "F6", "아웃점을 지금 위치로", "set_out_point", "타임코드",
           "재생 위치를 이 자막의 끝으로 삼는다."),
    Action("zoom_in", "Alt+=", "파형 확대", "zoom_in", "파형",
           "파형을 크게 본다. 타임코드를 프레임 단위로 다듬을 때 필요하다."),
    Action("zoom_out", "Alt+-", "파형 축소", "zoom_out", "파형",
           "파형을 넓게 본다. 전체 흐름을 훑을 때 쓴다."),
)

GROUPS = ("재생", "이동", "편집", "위치", "타임코드", "파형")


def _settings_file():
    from checker.paths import user_data

    folder = user_data()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "shortcuts.json"


def load() -> dict[str, str]:
    """기능 이름 -> 단축키. 바꾸지 않은 것은 기본값이 들어간다."""
    keys = {action.key: action.default for action in ACTIONS}
    path = _settings_file()
    if path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return keys
        for name, value in saved.items():
            if name in keys and isinstance(value, str):
                keys[name] = value
    return keys


def save(keys: dict[str, str]) -> None:
    """바꾼 것만 남긴다. 기본값이 나중에 바뀌면 따라가야 하기 때문이다."""
    changed = {action.key: keys[action.key] for action in ACTIONS
               if keys.get(action.key) and keys[action.key] != action.default}
    _settings_file().write_text(
        json.dumps(changed, ensure_ascii=False, indent=2), encoding="utf-8")


def conflicts(keys: dict[str, str]) -> list[tuple[str, str, str]]:
    """같은 키를 두 기능이 쓰면 알려 준다. (키, 기능1, 기능2)

    **말없이 덮어쓰지 않는다.** 겹친 키는 둘 중 하나만 듣는데, 어느 쪽이 들을지는
    사람이 알 수 없다.
    """
    seen: dict[str, str] = {}
    found = []
    titles = {action.key: action.title for action in ACTIONS}
    for name, key in keys.items():
        if not key:
            continue
        if key in seen:
            found.append((key, titles.get(seen[key], seen[key]), titles.get(name, name)))
        else:
            seen[key] = name
    return found
