"""주 화면. 왼쪽에 영상, 오른쪽에 자막 표.

**이 파일은 화면만 다룬다.** 자막을 읽고 쓰고 검사하는 일은 `checker/`가 한다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QTableView, QVBoxLayout, QWidget)

from checker.parsers import parse
from checker.writers import to_timecode, write_srt

from .model import SubtitleModel
from .player import Player, PlayerUnavailable
from .runtime import MPV_MISSING
from .waveform import Waveform

VIDEO_FILTER = "영상 (*.mp4 *.mkv *.mov *.avi *.ts *.m4v *.webm);;모든 파일 (*.*)"
SUBTITLE_FILTER = "자막 (*.srt *.vtt);;모든 파일 (*.*)"


class PeakWorker(QObject):
    """파형을 다른 실에서 만든다. 45분짜리를 읽는 동안 화면이 멈추면 안 된다."""

    done = Signal(object, int, int, int)
    failed = Signal(str)

    def __init__(self, video: str):
        super().__init__()
        self.video = video

    def run(self) -> None:
        try:
            from .peaks import load
            peaks, per_peak, rate, duration = load(Path(self.video))
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(peaks, per_peak, rate, duration)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("자막 편집기")
        self.resize(1280, 760)

        self._preview_loaded = False
        self.player: Player | None = None
        self.subtitle_path: Path | None = None
        self.model = SubtitleModel()
        # 편집 중인 내용을 영상에 얹기 위한 임시 파일. **원본과 따로 둔다** —
        # 미리 보기 때문에 원본이 바뀌면 안 된다.
        self._preview_path = Path(tempfile.gettempdir()) / "subtitle-editor-preview.srt"

        self._build()
        self._build_menu()

        # 재생 위치를 따라 표가 움직인다. 자막 작업은 "지금 무엇이 보이나"를
        # 계속 확인하는 일이라 이것이 없으면 눈이 두 곳을 오간다.
        # 편집할 때마다 파일을 다시 쓰면 타자 한 번에 디스크가 한 번 돈다.
        # 잠깐 모았다가 한꺼번에 갱신한다.
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.model.dataChanged.connect(lambda *_: self._preview_timer.start())
        self.model.modelReset.connect(lambda: self._preview_timer.start())

        self._follow = QTimer(self)
        self._follow.setInterval(100)
        self._follow.timeout.connect(self._sync_position)
        self._follow.start()

    # --- 화면 ---------------------------------------------------------
    def _build(self) -> None:
        self.video_area = QWidget()
        self.video_area.setMinimumSize(480, 270)
        self.video_area.setStyleSheet("background: #111;")
        self.video_area.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.video_area.setAttribute(Qt.WA_NativeWindow)

        self.position_label = QLabel("00:00:00,000 / 00:00:00,000")
        self.play_button = QPushButton("재생/멈춤 (Space)")
        self.play_button.clicked.connect(self.toggle_play)
        back = QPushButton("◀ 1프레임")
        back.clicked.connect(lambda: self.step(-1))
        forward = QPushButton("1프레임 ▶")
        forward.clicked.connect(lambda: self.step(1))

        controls = QHBoxLayout()
        controls.addWidget(back)
        controls.addWidget(self.play_button)
        controls.addWidget(forward)
        controls.addStretch(1)
        controls.addWidget(self.position_label)

        self.waveform = Waveform()
        self.waveform.seek_requested.connect(self._seek_to)
        self.waveform.cue_changed.connect(self._cue_changed)
        self.waveform.cue_selected.connect(self._select_cue)

        left = QVBoxLayout()
        left.addWidget(self.video_area, 1)
        left.addLayout(controls)
        left.addWidget(self.waveform)
        left_panel = QWidget()
        left_panel.setLayout(left)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.doubleClicked.connect(self._jump_to_row)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 60)
        self.table.horizontalHeader().setStretchLastSection(True)

        splitter = QSplitter()
        splitter.addWidget(left_panel)
        splitter.addWidget(self.table)
        splitter.setSizes([620, 660])
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("영상과 자막을 여세요")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("파일(&F)")
        for title, shortcut, slot in (
                ("영상 열기...", "Ctrl+O", self.open_video),
                ("자막 열기...", "Ctrl+Shift+O", self.open_subtitle),
                ("자막 저장", "Ctrl+S", self.save_subtitle),
        ):
            action = QAction(title, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            file_menu.addAction(action)

    # --- 파일 ---------------------------------------------------------
    def open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "영상 열기", "", VIDEO_FILTER)
        if not path:
            return
        if self.player is None:
            try:
                self.player = Player(int(self.video_area.winId()))
            except PlayerUnavailable as exc:
                QMessageBox.warning(self, "영상을 재생할 수 없습니다",
                                    f"{MPV_MISSING}\n\n{exc}")
                return
        self.player.open(path)
        self.statusBar().showMessage(f"영상: {Path(path).name}  {self.player.fps:.3f}fps"
                                     f" — 파형을 만드는 중입니다...")
        self._preview_loaded = False
        self._preview_timer.start()
        self._load_peaks(path)

    def open_subtitle(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "자막 열기", "", SUBTITLE_FILTER)
        if not path:
            return
        events = parse(Path(path))
        if not events:
            QMessageBox.warning(self, "자막을 읽지 못했습니다", path)
            return
        self.subtitle_path = Path(path)
        self.model.replace(events)
        self.waveform.set_events(self.model.events)
        self._preview_timer.start()
        self.statusBar().showMessage(f"자막 {len(events)}개: {self.subtitle_path.name}")

    def save_subtitle(self) -> None:
        if not self.model.events:
            return
        # **원본을 덮어쓰지 않는다.** 어디에 저장할지 사람이 정한다.
        suggested = str(self.subtitle_path.with_suffix(".edited.srt")) \
            if self.subtitle_path else "자막.srt"
        path, _ = QFileDialog.getSaveFileName(self, "자막 저장", suggested, SUBTITLE_FILTER)
        if not path:
            return
        write_srt(self.model.events, Path(path))
        self.statusBar().showMessage(f"저장했습니다: {path}")

    def _load_peaks(self, video: str) -> None:
        self._peak_thread = QThread(self)
        self._peak_worker = PeakWorker(video)
        self._peak_worker.moveToThread(self._peak_thread)
        self._peak_thread.started.connect(self._peak_worker.run)
        self._peak_worker.done.connect(self._peaks_ready)
        self._peak_worker.failed.connect(
            lambda why: self.statusBar().showMessage(f"파형을 만들지 못했습니다: {why}"))
        self._peak_worker.done.connect(self._peak_thread.quit)
        self._peak_worker.failed.connect(self._peak_thread.quit)
        self._peak_thread.start()

    def _peaks_ready(self, peaks, per_peak, rate, duration) -> None:
        self.waveform.set_peaks(peaks, per_peak, rate, duration)
        self.statusBar().showMessage(
            f"파형 준비 완료 — {duration / 60000:.1f}분. "
            "Ctrl+휠로 확대, 자막 가장자리를 끌어 인·아웃을 맞춥니다")

    def _refresh_preview(self) -> None:
        """편집 중인 자막을 영상에 얹는다."""
        if not self.player or not self.model.events:
            return
        try:
            write_srt(self.model.events, self._preview_path)
        except OSError:
            return
        if self._preview_loaded:
            self.player.reload_subtitles()
        else:
            self.player.set_subtitles(str(self._preview_path))
            self._preview_loaded = True

    def _seek_to(self, ms: int) -> None:
        if self.player:
            self.player.seek(ms)
        self.waveform.set_position(ms)

    def _cue_changed(self, index: int, start_ms: int, end_ms: int) -> None:
        """파형에서 끈 결과를 표에도 알린다. 자료는 하나다(같은 Event 객체)."""
        for row, event in enumerate(self.model.events):
            if event.index == index:
                left = self.model.index(row, 1)
                right = self.model.index(row, 3)
                self.model.dataChanged.emit(left, right, [Qt.DisplayRole])
                self.statusBar().showMessage(
                    f"#{index} {to_timecode(start_ms)} ~ {to_timecode(end_ms)}"
                    f"  ({(end_ms - start_ms) / 1000:.2f}초)")
                self._preview_timer.start()
                break

    def _select_cue(self, index: int) -> None:
        for row, event in enumerate(self.model.events):
            if event.index == index:
                self.table.selectRow(row)
                break

    # --- 재생 ---------------------------------------------------------
    def toggle_play(self) -> None:
        if self.player:
            self.player.toggle_pause()

    def step(self, frames: int) -> None:
        if self.player:
            self.player.step(frames)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self.toggle_play()
        elif event.key() == Qt.Key_Left:
            self.step(-1)
        elif event.key() == Qt.Key_Right:
            self.step(1)
        else:
            super().keyPressEvent(event)

    def _jump_to_row(self, index) -> None:
        event = self.model.event_at(index.row())
        if event and self.player:
            self.player.seek(event.start_ms)

    def _sync_position(self) -> None:
        if not self.player:
            return
        position = self.player.position_ms
        self.position_label.setText(
            f"{to_timecode(position)} / {to_timecode(self.player.duration_ms)}")
        self.waveform.set_position(position)
        row = self.model.row_for_time(position)
        if row >= 0 and row != self.table.currentIndex().row():
            self.table.selectRow(row)

    def closeEvent(self, event) -> None:
        if self.player:
            self.player.close()
        super().closeEvent(event)
