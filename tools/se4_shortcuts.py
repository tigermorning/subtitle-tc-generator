"""SE 4.x Settings.xml 에 강의 문서(구글 문서 «단축키» 탭) 단축키를 넣는다.

사용: python se4_shortcuts.py SETTINGS.xml   (SE를 닫은 뒤 실행, 원본은 .bak 로 보존)
같은 키를 쓰던 다른 기능은 비운다(키 충돌 방지).
"""
import sys, shutil
import xml.etree.ElementTree as ET

MAP = {
    "MainCreateStartDownEndUp": "F1",                 # 누르면 인점, 떼면 아웃점
    "GeneralGoToNextSubtitle": "F2",                  # 아래 자막으로 이동
    "MainCreateSetEnd": "F3",                         # 아웃점 잡기
    "MainInsertAfter": "F4",                          # 아래에 새 줄 삽입
    "MainEditFindNext": "F5",                         # 다음 찾기
    "MainAdjustExtendToNextSubtitle": "F7",           # 다음으로 확장
    "MainListViewGoToNextError": "F8",
    "MainListViewListErrors": "Control+F8",
    "WaveformSplit": "C",                             # 파형 위치에서 원문 나눔
    "MainListViewRemoveTimeCodes": "Control+T",
    "MainVideoPlayPauseToggle": "Escape",
    "GeneralGoToPreviousSubtitleAndFocusVideo": "PageUp",
    "GeneralGoToNextSubtitleAndFocusVideo": "PageDown",
    "MainAdjustSetStartAndOffsetTheRest": "Alt+A",    # 모든 인점 보정
    "GeneralMergeWithNext": "Alt+Space",              # 독백 병합
    "MainMergeDialogWithNext": "Alt+Shift+Space",     # 대화 병합(대시)
    "MainListViewSplit": "Control+Space",             # 자막 분리
    "MainListViewToggleDashes": "Control+OemMinus",
    "GeneralGoToBookmark": "Alt+B",
    "GeneralGoToNextBookmark": "Alt+N",
    "OpenDataFolder": "Control+Alt+Shift+D",
    "MainEditReplace": "Control+H",
    "MainEditGoToLineNumber": "Control+G",
    "MainVideo1FrameLeft": "Control+Shift+Left",
    "MainVideo1FrameRight": "Control+Shift+Right",
    "MainListViewAlignmentN2": "Alt+Down",
    "MainListViewAlignmentN8": "Alt+Up",
    "MainTextBoxUnbreak": "Control+Oem5",             # 줄바꿈 제거
}

path = sys.argv[1]
shutil.copyfile(path, path + ".bak")
tree = ET.parse(path)
sc = tree.getroot().find("Shortcuts")
keys = set(MAP.values())
cleared = []
for el in sc:
    if el.tag not in MAP and (el.text or "").strip() in keys:
        cleared.append(f"{el.tag}={el.text}")
        el.text = None
missing = []
for tag, key in MAP.items():
    el = sc.find(tag)
    if el is None:
        missing.append(tag)
        continue
    el.text = key
tree.write(path, encoding="utf-8", xml_declaration=True)
print("넣음", len(MAP) - len(missing), "/", len(MAP))
print("없는 항목", missing)
print("충돌로 비움", cleared)
