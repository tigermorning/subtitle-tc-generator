"""주 화면. 왼쪽에 영상, 오른쪽에 자막 표.

**이 파일은 화면만 다룬다.** 자막을 읽고 쓰고 검사하는 일은 `checker/`가 한다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QSplitter, QTableView,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from checker.parsers import parse
from checker.writers import to_timecode, write_srt

from . import jobs

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

        self._threads: list = []          # 실을 붙잡아 둔다. 놓으면 프로그램이 죽는다
        self._build()
        self._build_menu()
        self._build_pipeline()
        self._build_results()

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

    def _build_pipeline(self) -> None:
        """파이프라인 막대 — 엔진은 `checker/`에 있고 여기서는 부르기만 한다."""
        bar = self.addToolBar("작업")
        bar.setMovable(False)

        self.platform_box = QComboBox()
        self._reload_platforms()
        self.kind_box = QComboBox()
        self.kind_box.addItems(["translation", "sdh"])
        self.language_box = QComboBox()
        self.language_box.addItems(["en", "ko", "auto"])
        self.translate_check = QCheckBox("번역까지")
        self.korean_check = QCheckBox("한국어 교정")
        self.korean_check.setChecked(True)

        for label, widget in (("플랫폼", self.platform_box), ("종류", self.kind_box),
                              ("원어", self.language_box)):
            bar.addWidget(QLabel(f"  {label} "))
            bar.addWidget(widget)
        bar.addWidget(self.translate_check)
        bar.addWidget(self.korean_check)
        bar.addSeparator()

        bar.addSeparator()
        settings_action = QAction("작업 기준...", self)
        settings_action.triggered.connect(self.open_settings)
        bar.addAction(settings_action)
        bar.addSeparator()

        self.pipeline_buttons = []
        for title, slot in (("영상에서 자막 만들기", self.run_generate),
                            ("검사·교정", self.run_check),
                            ("번역", self.run_translate),
                            ("용어표", self.run_terms)):
            action = QAction(title, self)
            action.triggered.connect(slot)
            bar.addAction(action)
            self.pipeline_buttons.append(action)

    def _reload_platforms(self) -> None:
        """쓸 수 있는 작업 기준을 목록에 채운다.

        **사용자가 만든 발주처 기준도 함께 나온다.** 딸려 온 셋만 쓸 수 있으면
        다른 회사 일을 못 받는다.
        """
        from checker.profile import available_profiles

        current = self.platform_box.currentText()
        platforms = []
        for profile in available_profiles():
            if profile["language"] == "ko" and profile["platform"] not in platforms:
                platforms.append(profile["platform"])
        self.platform_box.clear()
        self.platform_box.addItems(platforms or ["netflix"])
        if current in platforms:
            self.platform_box.setCurrentText(current)

    def open_settings(self) -> None:
        """지금 걸려 있는 기준을 보여 주고, 발주처 기준으로 새로 저장하게 한다."""
        from .settings import SettingsDialog

        dialog = SettingsDialog(self.platform_box.currentText(),
                                self.kind_box.currentText(), self)
        dialog.exec()
        if dialog.saved_as:
            self._reload_platforms()
            self.platform_box.setCurrentText(dialog.saved_as)
            self.statusBar().showMessage(f"작업 기준을 '{dialog.saved_as}'로 바꿨습니다")

    def _build_results(self) -> None:
        """지적 목록. **두 번 누르면 그 자막으로 간다** — 목록과 영상이 이어져야
        사람이 확인할 수 있다."""
        self.results = QTableWidget(0, 3)
        self.results.setHorizontalHeaderLabels(["자막", "규칙", "내용"])
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.setColumnWidth(0, 60)
        self.results.setColumnWidth(1, 70)
        self.results.doubleClicked.connect(self._jump_to_violation)

        dock = QDockWidget("검사 결과", self)
        dock.setWidget(self.results)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        dock.hide()
        self.results_dock = dock

    def _show_violations(self, violations) -> None:
        self.results.setRowCount(len(violations))
        for row, violation in enumerate(violations):
            mark = "자동" if violation.get("auto_fixable") else "확인"
            self.results.setItem(row, 0, QTableWidgetItem(str(violation["event_index"])))
            self.results.setItem(row, 1, QTableWidgetItem(f"{violation['rule_id']} {mark}"))
            detail = violation.get("detail") or violation.get("message") or ""
            self.results.setItem(row, 2, QTableWidgetItem(str(detail)[:120]))
        self.results_dock.setVisible(bool(violations))

    def _jump_to_violation(self, index) -> None:
        item = self.results.item(index.row(), 0)
        if not item:
            return
        number = int(item.text())
        for row, event in enumerate(self.model.events):
            if event.index == number:
                self.table.selectRow(row)
                if self.player:
                    self.player.seek(event.start_ms)
                break

    # --- 파이프라인 ---------------------------------------------------
    def _profile(self):
        from checker import load_profile
        return load_profile(self.platform_box.currentText(), "ko",
                            self.kind_box.currentText())

    def _corrector_path(self) -> str | None:
        import os
        return os.environ.get("KSC_PATH")

    def _busy(self, busy: bool, what: str = "") -> None:
        for action in self.pipeline_buttons:
            action.setEnabled(not busy)
        if what:
            self.statusBar().showMessage(what)

    def _start(self, job, on_done, what: str) -> None:
        self._busy(True, what)

        def done(result):
            self._busy(False)
            on_done(result)

        def failed(why):
            self._busy(False)
            self.statusBar().showMessage(f"실패: {why}")
            QMessageBox.warning(self, "작업을 마치지 못했습니다", why)

        thread = jobs.start(job, done,
                            lambda m: self.statusBar().showMessage(m), failed)
        self._threads.append(thread)

    def run_generate(self) -> None:
        if not self.player or not getattr(self, "_video_path", None):
            QMessageBox.information(self, "영상이 필요합니다", "먼저 영상을 여세요.")
            return
        script = None
        if self.kind_box.currentText() == "translation":
            path, _ = QFileDialog.getOpenFileName(
                self, "원어 대본 (없으면 취소)", "", "대본 (*.txt *.md);;모든 파일 (*.*)")
            script = Path(path) if path else None

        job = jobs.GenerateJob(Path(self._video_path), self._profile(), script,
                               self.language_box.currentText(),
                               self.translate_check.isChecked())

        def done(draft):
            self.model.replace(draft.events)
            self.waveform.set_events(self.model.events)
            self._preview_timer.start()
            notes = len(draft.notes)
            self.statusBar().showMessage(
                f"자막 {len(draft.events)}개를 만들었습니다"
                + (f" — 봐야 할 자리 {notes}곳" if notes else ""))
            if draft.notes:
                self._show_violations([
                    {"event_index": i, "rule_id": "확인", "detail": note,
                     "auto_fixable": False} for i, note in draft.notes])

        self._start(job, done, "영상에서 자막을 만드는 중입니다...")

    def run_check(self) -> None:
        if not self.model.events:
            return
        job = jobs.CheckJob(self.model.events, self._profile(), fix=True,
                            korean=self.korean_check.isChecked(),
                            corrector_path=self._corrector_path())

        def done(result):
            events, violations = result
            self.model.replace(events)
            self.waveform.set_events(self.model.events)
            self._preview_timer.start()
            self._show_violations(violations)
            self.statusBar().showMessage(f"남은 지적 {len(violations)}건")

        self._start(job, done, "검사·교정 중입니다...")

    def run_translate(self) -> None:
        if not self.model.events:
            return
        from checker.knp import find_for
        knp = find_for(self.subtitle_path) if self.subtitle_path else None
        job = jobs.TranslateJob(self.model.events, self._profile(),
                                passes=3 if self.translate_check.isChecked() else 1,
                                knp=knp)

        def done(events):
            self.model.replace(events)
            self.waveform.set_events(self.model.events)
            self._preview_timer.start()
            self.statusBar().showMessage(
                f"번역했습니다 — 타임코드는 그대로입니다({len(events)}개)")

        self._start(job, done, "한국어로 옮기는 중입니다...")

    def run_terms(self) -> None:
        if not self.model.events:
            return
        from checker.knp import find_for
        base = self.subtitle_path or Path("용어표.srt")
        out = base.with_suffix(".terms.tsv")
        job = jobs.TermsJob(self.model.events, out, web=True, explain=True,
                            corrector_path=self._corrector_path(),
                            knp=find_for(base) if self.subtitle_path else None)

        def done(result):
            terms, path = result
            filled = sum(1 for t in terms if t.korean)
            self.statusBar().showMessage(
                f"용어 {len(terms)}개 중 {filled}개에 표기를 채웠습니다: {path.name}")
            self._show_violations([
                {"event_index": 0, "rule_id": t.kind,
                 "detail": f"{t.source} -> {t.korean or '확인 필요'}  {t.meaning}",
                 "auto_fixable": bool(t.korean)} for t in terms])

        self._start(job, done, "용어를 조사하는 중입니다...")

    def show_diagnosis(self) -> None:
        """무엇을 찾았고 무엇을 못 찾았는지. 조용히 안 되는 것을 없앤다."""
        from .diagnose import as_text
        box = QMessageBox(self)
        box.setWindowTitle("진단")
        box.setText("<pre>" + as_text().replace("<", "&lt;") + "</pre>")
        box.exec()

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

        help_menu = self.menuBar().addMenu("도움말(&H)")
        diagnosis = QAction("진단...", self)
        diagnosis.triggered.connect(self.show_diagnosis)
        help_menu.addAction(diagnosis)

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
        self._video_path = path
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
        try:
            if self._preview_loaded:
                self.player.reload_subtitles()
            else:
                self.player.set_subtitles(str(self._preview_path))
                self._preview_loaded = True
        except Exception as exc:
            # **조용히 실패하지 않는다.** 자막이 안 뜨는데 이유를 모르면 사람이
            # 프로그램을 탓하게 된다(실제로 그랬다).
            self.statusBar().showMessage(f"영상에 자막을 얹지 못했습니다: {exc}")

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
        # 창 크기가 바뀌면 영상이 차지하는 비율도 바뀐다. 자막 크기를 따라 맞춘다.
        self.player.fit_subtitle_scale()
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
