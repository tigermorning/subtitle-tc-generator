"""자막 목록을 화면에 붙이는 표 모델.

`checker.model.Event`를 그대로 담는다 — 화면용 자료 구조를 따로 만들지 않는다.
따로 만들면 저장할 때마다 옮겨 담아야 하고, 그 자리에서 값이 어긋난다.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from checker.model import Event
from checker.writers import to_timecode

# **자막은 두 벌이다.** 원어와 번역을 나란히 놓아야 번역을 검토할 수 있다
# (사용자 지적 2026-08-12). SE의 '원본 자막 열기'가 하던 일이다.
COLUMNS = ("#", "시작", "끝", "길이", "원어", "자막")
SOURCE_COLUMN = 4
TEXT_COLUMN = 5


class SubtitleModel(QAbstractTableModel):
    def __init__(self, events: list[Event] | None = None):
        super().__init__()
        self.events: list[Event] = events or []
        # 자막 번호 -> 원어. 번역 전 글자를 여기 남겨 둔다.
        self.sources: dict[int, str] = {}

    # --- 읽기 ---------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.events)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return None
        return COLUMNS[section]

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        event = self.events[index.row()]
        column = index.column()

        if role in (Qt.DisplayRole, Qt.EditRole):
            if column == 0:
                return event.index
            if column == 1:
                return to_timecode(event.start_ms)
            if column == 2:
                return to_timecode(event.end_ms)
            if column == 3:
                return f"{(event.end_ms - event.start_ms) / 1000:.2f}"
            if column == SOURCE_COLUMN:
                return self.sources.get(event.index, "").replace("\n", " ⏎ ")
            # 표에서는 줄바꿈을 눈에 보이게 둔다. 두 줄짜리 자막을 한 줄로 보면
            # 줄바꿈 위치가 맞는지 알 수 없다.
            return event.text.replace("\n", " ⏎ ")

        if role == Qt.TextAlignmentRole and column in (0, 1, 2, 3):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    # --- 쓰기 ---------------------------------------------------------
    def flags(self, index: QModelIndex):
        base = super().flags(index)
        return base | Qt.ItemIsEditable if index.column() == TEXT_COLUMN else base

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if role != Qt.EditRole or index.column() != TEXT_COLUMN:
            return False
        self.events[index.row()].text = str(value).replace(" ⏎ ", "\n")
        self.dataChanged.emit(index, index, [Qt.DisplayRole])
        return True

    def replace(self, events: list[Event], sources: dict[int, str] | None = None) -> None:
        """자막을 갈아 끼운다. `sources`를 주면 원어 칸을 채운다.

        원어를 **주지 않으면 지우지 않는다** — 검사·교정을 돌려도 원어는 남아야
        번역을 견줄 수 있다.
        """
        self.beginResetModel()
        self.events = events
        if sources is not None:
            self.sources = sources
        self.endResetModel()

    def remember_sources(self) -> dict[int, str]:
        """지금 글자를 원어로 기억해 둔다. 번역 직전에 부른다."""
        return {e.index: e.text for e in self.events}

    def event_at(self, row: int) -> Event | None:
        return self.events[row] if 0 <= row < len(self.events) else None

    def row_for_time(self, ms: int) -> int:
        """그 시각에 보이는 자막의 줄 번호. 없으면 -1."""
        for i, event in enumerate(self.events):
            if event.start_ms <= ms < event.end_ms:
                return i
        return -1
