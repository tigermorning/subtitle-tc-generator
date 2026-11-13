"""한국어 교정 설정 창 — 교정기 웹앱 «2단계 · 교정 옵션»과 같은 칸·같은 이름.

값의 뜻·기본값·저장은 `checker/korean_settings.py`가 갖는다. 이 창은 그리고 받기만 한다.
발주처 프로파일이 정한 칸(화자명·어조 부호, 말줄임표)은 그 값으로 채워 열리고,
사용자가 바꾼 칸만 작품 작업 폴더에 저장된다.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QRadioButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout)

from checker.korean_settings import (
    DIALECT_MODES, DOC_TYPES, ELLIPSIS_STYLES, QUOTE_STYLES, SPACING_MODES,
    KoreanSettings, parse_names)


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #777;")
    return label


def _combo(choices, value: str) -> QComboBox:
    box = QComboBox()
    for key, title in choices:
        box.addItem(title, key)
    index = box.findData(value)
    box.setCurrentIndex(index if index >= 0 else 0)
    return box


class KoreanSettingsDialog(QDialog):
    """`settings`(지금 적용될 값)로 열리고, OK면 `result_settings()`가 고친 값을 준다."""

    def __init__(self, settings: KoreanSettings, regions: list[str], where: str,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("한국어 교정 설정")
        self.setObjectName("korean_settings")
        self._regions = list(regions)
        layout = QVBoxLayout(self)
        layout.addWidget(_note(where))

        # 사용 목적
        purpose = QGroupBox("사용 목적")
        row = QHBoxLayout(purpose)
        self.doc_group = QButtonGroup(self)
        self.doc_buttons = {}
        for key, title in DOC_TYPES:
            button = QRadioButton(title)
            button.setChecked(settings.doc_type == key)
            self.doc_group.addButton(button)
            self.doc_buttons[key] = button
            row.addWidget(button)
        row.addStretch(1)
        layout.addWidget(purpose)

        # 구두점 표기
        punct = QGroupBox("구두점 표기 (자막 모드에만 적용 · 납품처 요구에 맞춰 고르세요)")
        form = QFormLayout(punct)
        self.ellipsis_box = _combo(ELLIPSIS_STYLES, settings.ellipsis)
        self.quotes_box = _combo(QUOTE_STYLES, settings.quotes)
        form.addRow("말줄임표", self.ellipsis_box)
        form.addRow("따옴표", self.quotes_box)
        self.punct_group = punct
        layout.addWidget(punct)

        # 자막 편집 표지
        marks = QGroupBox("자막 편집 표지 (자막 모드에만 적용 · 여기 적은 표지는 교정하지 않습니다)")
        form = QFormLayout(marks)
        self.marker_edits = {}
        for key, title, example in (
                ("screen_text_marker", "화면자막 표기", '"  또는  @'),
                ("line_break_marker", "줄바꿈 표기", "|"),
                ("position_marker", "자막 위치 표기", "{\\an8}"),
                ("speaker_bracket", "화자명 표기", "[]"),
                ("tone_bracket", "어조·지문 표기", "()")):
            edit = QLineEdit(getattr(settings, key))
            edit.setPlaceholderText(example)
            edit.setObjectName(key)
            self.marker_edits[key] = edit
            form.addRow(title, edit)
        form.addRow(_note("비워 두면 그 표지는 쓰지 않는 것으로 봅니다(화자명·어조는 "
                          "대괄호). 발주처 기준이 정한 부호가 미리 채워져 있습니다."))
        self.marker_group = marks
        layout.addWidget(marks)

        # 띄어쓰기 기준
        spacing = QGroupBox("띄어쓰기 기준 (보조 용언, 한글 맞춤법 제47항)")
        row = QHBoxLayout(spacing)
        self.spacing_group = QButtonGroup(self)
        self.spacing_buttons = {}
        for key, title in SPACING_MODES:
            button = QRadioButton(title)
            button.setChecked(settings.spacing_mode == key)
            self.spacing_group.addButton(button)
            self.spacing_buttons[key] = button
            row.addWidget(button)
        row.addStretch(1)
        layout.addWidget(spacing)

        # 고유명사
        names = QGroupBox("[선택사항] 고유명사·요리·음료 이름 (한 줄에 하나씩 작성)")
        col = QVBoxLayout(names)
        self.names_edit = QPlainTextEdit("\n".join(settings.names))
        self.names_edit.setPlaceholderText("연실\n철수\n탄두리치킨")
        self.names_edit.setFixedHeight(80)
        col.addWidget(self.names_edit)
        col.addWidget(_note("여기 적은 단어는 절대 잘못 쪼개지 않습니다. 문서에서 3번 이상 "
                            "반복되는 단어는 적지 않아도 자동으로 인식됩니다."))
        layout.addWidget(names)

        # 사투리
        dialect = QGroupBox("[선택사항] 사투리 설정")
        col = QVBoxLayout(dialect)
        row = QHBoxLayout()
        row.addWidget(QLabel("문서 전체"))
        self.region_box = self._region_combo(settings.dialect_region)
        self.mode_box = _combo(DIALECT_MODES, settings.dialect_mode)
        row.addWidget(self.region_box)
        row.addWidget(self.mode_box)
        row.addStretch(1)
        col.addLayout(row)
        self.speaker_table = QTableWidget(0, 3)
        self.speaker_table.setHorizontalHeaderLabels(["화자", "지역", "모드"])
        self.speaker_table.horizontalHeader().setStretchLastSection(True)
        self.speaker_table.setFixedHeight(110)
        for speaker, spec in settings.speaker_dialects.items():
            self._add_speaker_row(speaker, spec.get("region", ""), spec.get("mode", "protect"))
        col.addWidget(self.speaker_table)
        row = QHBoxLayout()
        self.new_speaker = QLineEdit()
        self.new_speaker.setPlaceholderText("화자 이름")
        add = QPushButton("+ 화자 추가")
        add.clicked.connect(self._add_clicked)
        remove = QPushButton("선택 화자 빼기")
        remove.clicked.connect(self._remove_clicked)
        for widget in (self.new_speaker, add, remove):
            row.addWidget(widget)
        col.addLayout(row)
        if not self._regions:
            col.addWidget(_note("교정기에서 사투리 지역 목록을 읽지 못했습니다 — 지역은 "
                                "«설정 안함»만 고를 수 있습니다."))
        layout.addWidget(dialect)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for button in self.doc_buttons.values():
            button.toggled.connect(self._sync_doc_type)
        self._sync_doc_type()

    # ------------------------------------------------------------ 칸
    def _region_combo(self, value: str, auto: bool = False) -> QComboBox:
        box = QComboBox()
        box.addItem("설정 안함 (자동 감지)" if auto else "설정 안함", "")
        for region in self._regions:
            box.addItem(region, region)
        index = box.findData(value)
        box.setCurrentIndex(index if index >= 0 else 0)
        return box

    def _add_speaker_row(self, speaker: str, region: str = "", mode: str = "protect") -> None:
        speaker = speaker.strip()
        if not speaker:
            return
        for row in range(self.speaker_table.rowCount()):
            if self.speaker_table.item(row, 0).text() == speaker:
                return
        row = self.speaker_table.rowCount()
        self.speaker_table.insertRow(row)
        self.speaker_table.setItem(row, 0, QTableWidgetItem(speaker))
        self.speaker_table.setCellWidget(row, 1, self._region_combo(region, auto=True))
        modes = (("protect", "기본: 사투리 보호 (교정·플래그 안 함)"),) + DIALECT_MODES[1:]
        self.speaker_table.setCellWidget(row, 2, _combo(modes, mode))

    def _add_clicked(self) -> None:
        self._add_speaker_row(self.new_speaker.text())
        self.new_speaker.clear()

    def _remove_clicked(self) -> None:
        row = self.speaker_table.currentRow()
        if row >= 0:
            self.speaker_table.removeRow(row)

    def _sync_doc_type(self) -> None:
        """웹앱처럼 일반 글이면 자막 전용 칸을 감춘다 — 보이는데 안 먹는 설정을 없앤다."""
        subtitle = self.doc_buttons["subtitle"].isChecked()
        self.punct_group.setVisible(subtitle)
        self.marker_group.setVisible(subtitle)

    # ------------------------------------------------------------ 결과
    def result_settings(self) -> KoreanSettings:
        doc_type = next(k for k, b in self.doc_buttons.items() if b.isChecked()) \
            if any(b.isChecked() for b in self.doc_buttons.values()) else "subtitle"
        spacing = next((k for k, b in self.spacing_buttons.items() if b.isChecked()),
                       "principle")
        speakers = {}
        for row in range(self.speaker_table.rowCount()):
            name = self.speaker_table.item(row, 0).text().strip()
            region = self.speaker_table.cellWidget(row, 1).currentData() or ""
            mode = self.speaker_table.cellWidget(row, 2).currentData() or "protect"
            if name:
                speakers[name] = {"region": region, "mode": mode}
        return KoreanSettings(
            doc_type=doc_type,
            ellipsis=self.ellipsis_box.currentData(),
            quotes=self.quotes_box.currentData(),
            screen_text_marker=self.marker_edits["screen_text_marker"].text(),
            line_break_marker=self.marker_edits["line_break_marker"].text(),
            position_marker=self.marker_edits["position_marker"].text(),
            speaker_bracket=self.marker_edits["speaker_bracket"].text(),
            tone_bracket=self.marker_edits["tone_bracket"].text(),
            spacing_mode=spacing,
            names=parse_names(self.names_edit.toPlainText()),
            dialect_region=self.region_box.currentData() or "",
            dialect_mode=self.mode_box.currentData() or "protect",
            speaker_dialects=speakers,
        ).normalized()


__all__ = ["KoreanSettingsDialog"]
