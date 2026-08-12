"""주 화면. 왼쪽에 영상, 오른쪽에 자막 표.

**이 파일은 화면만 다룬다.** 자막을 읽고 쓰고 검사하는 일은 `checker/`가 한다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QLabel, QSizePolicy,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSplitter, QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

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
    def __init__(self, restore: bool = True):
        """`restore=False`면 지난번 배치를 되살리지 않는다.

        시험에서 필요하다. 사람이 쓰던 설정이 시험 결과를 바꾸면 통과·실패가
        기계마다 달라진다(실제로 그랬다).
        """
        super().__init__()
        self._restore = restore
        self.setWindowTitle("자막 및 TC 생성기")
        self.resize(1280, 760)

        self._preview_loaded = False
        self.player: Player | None = None
        self.subtitle_path: Path | None = None
        self.model = SubtitleModel()
        # 편집 중인 내용을 영상에 얹기 위한 임시 파일. **원본과 따로 둔다** —
        # 미리 보기 때문에 원본이 바뀌면 안 된다.
        self._preview_path = Path(tempfile.gettempdir()) / "subtitle-tc-generator-preview.srt"

        self._threads: list = []          # 실을 붙잡아 둔다. 놓으면 프로그램이 죽는다
        self._build()
        self._build_menu()
        self._build_pipeline()
        self._build_results()
        self._build_progress()
        self._build_shortcuts()
        self.apply_prefs()

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
        # **작게 줄일 수 있어야 한다.** 최소 크기를 크게 잡으면 파형이나 표를 아무리
        # 늘리려 해도 영상이 자리를 내주지 않는다(사용자 지적 2026-08-12).
        # 타임코드만 잡을 때는 영상이 손바닥만 해도 된다.
        self.video_area.setMinimumSize(120, 68)
        self.video_area.setStyleSheet("background: #111;")
        self.video_area.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.video_area.setAttribute(Qt.WA_NativeWindow)

        self.position_label = QLabel("00:00:00,000 / 00:00:00,000")
        self.position_label.setMinimumWidth(0)
        self.position_label.setToolTip("재생 위치 / 전체 길이")
        self.play_button = QPushButton("▶ ‖")
        self.play_button.setToolTip("재생 / 일시정지 (Esc, Space)")
        self.play_button.clicked.connect(self.toggle_play)
        back = QPushButton("◀|")
        back.setToolTip("1프레임 뒤로 (Ctrl+Shift+←)")
        back.clicked.connect(lambda: self.step(-1))
        forward = QPushButton("|▶")
        forward.setToolTip("1프레임 앞으로 (Ctrl+Shift+→)")
        forward.clicked.connect(lambda: self.step(1))

        controls = QHBoxLayout()
        controls.setContentsMargins(2, 0, 2, 0)
        controls.setSpacing(2)
        controls.addWidget(back)
        controls.addWidget(self.play_button)
        controls.addWidget(forward)
        zoom_in = QPushButton("＋")
        zoom_in.setToolTip("파형 확대 (Alt+=, Ctrl+휠)")
        zoom_in.clicked.connect(lambda: self.waveform.zoom(0.7))
        zoom_out = QPushButton("－")
        zoom_out.setToolTip("파형 축소 (Alt+-)")
        zoom_out.clicked.connect(lambda: self.waveform.zoom(1.4))
        controls.addWidget(zoom_in)
        controls.addWidget(zoom_out)
        controls.addStretch(1)
        controls.addWidget(self.position_label)

        # **단추와 글자가 폭을 잡아먹으면 영상을 줄일 수 없다.** 줄어들 수 있게
        # 해 둔다 — 좁아지면 잘려도 된다. 조작은 단축키로도 되고, 설명은 툴팁에 있다.
        for button in (self.play_button, back, forward, zoom_in, zoom_out):
            button.setMaximumWidth(42)
            button.setMinimumWidth(20)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.setFlat(True)
        self.position_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.waveform = Waveform()
        self.waveform.seek_requested.connect(self._seek_to)
        self.waveform.cue_changed.connect(self._cue_changed)
        self.waveform.cue_selected.connect(self._select_cue)

        # **면적을 사람이 정한다.** 타임코드를 미세하게 볼 때는 파형을 크게,
        # 번역을 다듬을 때는 표를 크게 쓴다(사용자 지적 2026-08-12).
        control_bar = QWidget()
        control_bar.setLayout(controls)
        control_bar.setMinimumWidth(0)

        video_panel = QWidget()
        video_panel.setMinimumWidth(0)
        video_box = QVBoxLayout(video_panel)
        video_box.setContentsMargins(0, 0, 0, 0)
        video_box.setSpacing(2)
        video_box.addWidget(self.video_area, 1)
        video_box.addWidget(control_bar)

        # **파형은 아래 전체 폭을 쓴다.** 자막 표는 스크롤하며 보면 되니 넓을 필요가
        # 없지만, 파형은 넓을수록 시간이 길게 펼쳐져 경계를 잡기 쉽다(사용자 지적
        # 2026-08-12). SE도 같은 꼴이다 — 위에 영상과 목록, 아래에 파형.
        self.top_splitter = QSplitter(Qt.Horizontal)
        self.top_splitter.setHandleWidth(8)
        self.top_splitter.setChildrenCollapsible(False)
        self.top_splitter.addWidget(video_panel)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.doubleClicked.connect(self._jump_to_row)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 60)
        self.table.setColumnWidth(4, 240)      # 원어
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumWidth(0)
        self.table.setMinimumHeight(0)
        self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        self.top_splitter.addWidget(self.table)
        self.top_splitter.setSizes([620, 660])

        self.main_splitter = QSplitter(Qt.Vertical)
        self.main_splitter.setHandleWidth(8)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self.top_splitter)
        self.main_splitter.addWidget(self.waveform)
        self.main_splitter.setSizes([460, 300])
        # **잡이가 보여야 잡는다.** 가는 선은 있는 줄도 모른다.
        self.setStyleSheet(
            "QSplitter::handle { background: #3a3f4b; }"
            "QSplitter::handle:hover { background: #5b8dd9; }")
        self.setCentralWidget(self.main_splitter)
        if self._restore:
            self._restore_layout()
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
        # 자막 만들 때 번역까지 함께 할지. **한국어 교정 체크박스는 없앴다** —
        # 버튼(② 한국어 교정)이 되었으므로 체크박스로 또 있으면 어느 쪽이 언제 걸리는지
        # 화면만 봐서는 알 수 없다. 단계는 버튼 하나가 하나씩 맡는다.
        self.translate_check = QCheckBox("만들 때 번역까지")

        for label, widget in (("플랫폼", self.platform_box), ("종류", self.kind_box),
                              ("원어", self.language_box)):
            bar.addWidget(QLabel(f"  {label} "))
            bar.addWidget(widget)
        bar.addWidget(self.translate_check)
        bar.addSeparator()

        bar.addSeparator()
        settings_action = QAction("작업 기준...", self)
        settings_action.triggered.connect(self.open_settings)
        bar.addAction(settings_action)
        bar.addSeparator()

        # **버튼을 `STAGES`에서 만든다.** 목록이 유일한 사실이고 화면은 그것을 그린다 —
        # 번역 QA 같은 단계를 붙일 때 `pipeline.STAGES`에 한 줄만 더하면 된다.
        from checker.pipeline import STAGES

        slots = {"generate": self.run_generate, "korean": self.run_korean,
                 "check": self.run_check, "translate": self.run_translate,
                 "terms": self.run_terms}
        self.stage_actions: dict = {}
        for stage in STAGES:
            action = QAction(stage.label, self)
            action.setToolTip(stage.note)
            action.triggered.connect(slots[stage.id])
            bar.addAction(action)
            self.stage_actions[stage.id] = action
        # 옛 이름을 쓰던 자리가 남아 있어도 깨지지 않게 한다.
        self.pipeline_buttons = list(self.stage_actions.values())
        self._refresh_stages()

    NEW_PROFILE = "＋ 새 기준 만들기..."

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
        self.platform_box.blockSignals(True)
        self.platform_box.clear()
        self.platform_box.addItems(platforms or ["netflix"])
        # **원하는 만큼 기준을 더 만들 수 있어야 한다.** 딸려 온 셋에 갇히면
        # 다른 회사 일을 못 받는다(사용자 지적 2026-08-12).
        self.platform_box.addItem(self.NEW_PROFILE)
        if current in platforms:
            self.platform_box.setCurrentText(current)
        self.platform_box.blockSignals(False)
        # 한 번만 잇는다. 끊었다 다시 이으면 Qt가 경고를 뱉는다.
        if not getattr(self, "_platform_connected", False):
            self.platform_box.currentTextChanged.connect(self._platform_changed)
            self._platform_connected = True

    def _platform_changed(self, text: str) -> None:
        if text == self.NEW_PROFILE:
            # 고른 순간 목록을 되돌려 둔다 — 창을 닫아도 이상한 값이 남지 않는다.
            self.platform_box.setCurrentIndex(0)
            self.open_settings()

    def open_settings(self) -> None:
        """지금 걸려 있는 기준을 보여 주고, 발주처 기준으로 새로 저장하게 한다."""
        from .settings import SettingsDialog

        dialog = SettingsDialog(self.platform_box.currentText(),
                                self.kind_box.currentText(), self)
        dialog.exec()
        self.reload_shortcuts()
        self.apply_prefs()
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

    def apply_prefs(self) -> None:
        """설정을 화면에 반영한다. 저장하자마자 보이게 — 다시 켜게 하지 않는다."""
        from . import prefs

        values = prefs.load()
        self.waveform.ms_per_pixel = float(values["waveform_ms_per_pixel"])
        self.waveform.follow = bool(values["waveform_follow"])
        self.waveform.show_speech = bool(values["waveform_show_speech"])
        self.waveform.show_shots = bool(values["waveform_show_shots"])
        self.waveform.update()
        self.language_box.setCurrentText(values["whisper_language"])
        self._prefs = values

    def _build_progress(self) -> None:
        """**돌고 있는지 눈에 보여야 한다.**

        상태줄 글자만 바뀌면 사람은 멈춘 줄 안다(사용자 지적 2026-08-12). 전사는
        몇 분씩 걸리고 그동안 겉으로는 조용하다. 그래서 셋을 함께 보여 준다.

            움직이는 막대   지금 일하고 있다
            흐른 시간      얼마나 됐나
            진행 기록      무엇을 하는 중인가 (한 줄씩 쌓인다)
        """
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)         # 끝을 모르는 일이라 계속 움직인다
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.elapsed_label = QLabel("")
        self.statusBar().addPermanentWidget(self.elapsed_label)
        self.statusBar().addPermanentWidget(self.progress_bar)

        self.progress_log = QPlainTextEdit()
        self.progress_log.setReadOnly(True)
        self.progress_log.setMaximumBlockCount(500)
        dock = QDockWidget("진행 기록", self)
        dock.setWidget(self.progress_log)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.progress_dock = dock
        dock.hide()

        self._elapsed = QTimer(self)
        self._elapsed.setInterval(1000)
        self._elapsed.timeout.connect(self._tick)
        self._started_at = 0.0

    def _tick(self) -> None:
        import time
        seconds = int(time.time() - self._started_at)
        self.elapsed_label.setText(f"{seconds // 60}:{seconds % 60:02d} 경과")

    def _note(self, text: str) -> None:
        """진행 한 줄. 상태줄·기록 창·로그 파일에 함께 남긴다.

        **로그 파일에도 남기는 이유**: 화면 기록은 프로그램을 닫으면 사라진다.
        "눌렀는데 아무 일도 안 일어난다"는 신고가 왔을 때(2026-08-12) 로그에는
        시작 줄밖에 없어 무엇이 막았는지 알 수 없었다.
        """
        from .log import write as log

        log(text)
        self.statusBar().showMessage(text)
        self.progress_log.appendPlainText(text)

    def _refuse(self, title: str, why: str) -> None:
        """일을 시작하지 않고 돌아설 때. **말없이 돌아서지 않는다.**

        조용히 `return`하면 사용자에게는 버튼이 죽은 것으로 보이고, 로그에도
        아무것도 없어 다음 사람이 원인을 찾지 못한다.
        """
        self._note(f"{title}: {why}")
        QMessageBox.information(self, title, why)

    # --- 파이프라인 ---------------------------------------------------
    def _profile(self):
        from checker import load_profile
        return load_profile(self.platform_box.currentText(), "ko",
                            self.kind_box.currentText())

    def _corrector_path(self) -> str | None:
        """교정기 자리. 옆에 있으면 그냥 쓴다 — 설정을 만들게 하지 않는다."""
        from checker.korean import find_corrector
        found = find_corrector()
        return str(found) if found else None

    def _busy(self, busy: bool, what: str = "") -> None:
        import time

        for action in self.pipeline_buttons:
            action.setEnabled(not busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self._started_at = time.time()
            self._elapsed.start()
            self.progress_dock.show()
            self.progress_log.appendPlainText("")
            if what:
                self._note(what)
        else:
            self._elapsed.stop()
            seconds = int(time.time() - self._started_at)
            self.elapsed_label.setText(f"{seconds // 60}:{seconds % 60:02d} 걸림")

    def _start(self, job, on_done, what: str) -> None:
        self._busy(True, what)

        def done(result):
            self._busy(False)
            on_done(result)

        def failed(why):
            self._busy(False)
            self._note(f"실패: {why}")
            QMessageBox.warning(self, "작업을 마치지 못했습니다", why)

        thread = jobs.start(job, done, self._note, failed)
        self._threads.append(thread)

    def run_generate(self) -> None:
        self._note("[① 자막 만들기] 눌림")
        if not self._stage_guard("generate"):
            return
        if not self.player:
            # **재생기가 없어도 자막은 만들 수 있다.** 전사는 ffmpeg가 하지 mpv가
            # 하지 않는다. 재생기가 없다고 막으면, libmpv를 못 찾은 컴퓨터에서는
            # 이 프로그램의 본래 기능을 통째로 못 쓴다.
            self._note("재생기가 없지만 전사는 ffmpeg가 하므로 그대로 진행합니다")

        script = None
        if self.kind_box.currentText() == "translation":
            from checker.script import file_filter
            self._note("원어 대본을 고르는 창을 엽니다 (없으면 취소)")
            path, _ = QFileDialog.getOpenFileName(
                self, "원어 대본 (없으면 취소)", "", file_filter())
            script = Path(path) if path else None
            self._note(f"대본: {script.name if script else '없음'}")

        job = jobs.GenerateJob(Path(self._video_path), self._profile(), script,
                               self.language_box.currentText(),
                               self.translate_check.isChecked())

        # **어느 경로로 도는지 먼저 말한다.** 대본이 있으면 "전사가 왜 필요한가"라는
        # 의문이 생기는데, 전사는 글자를 얻으려는 것이 아니라 **타임코드를 잡고 대본에
        # 없는 대사를 찾으려는 것**이다(`checker/align.py` 서두). 그 사실을 알려 주면
        # 기다리는 이유가 납득된다.
        if script:
            self._note("대본과 전사를 대조합니다 — 전사는 타임코드를 잡고 "
                       "대본에 없는 대사를 찾는 데 씁니다. 어긋난 자리는 표시해 드립니다.")
        else:
            self._note("대본이 없으므로 전사한 글자로 자막을 만듭니다 (SDH 경로).")

        # **얼마나 걸릴지 미리 말해 준다.** 모르면 멈춘 줄 안다. 전사는 실측
        # 20배속쯤이고, 번역은 자막 수에 비례해 그보다 훨씬 느리다.
        minutes = ((self.player.duration_ms if self.player else 0) or 0) / 60000
        guess = f"전사에 {max(1, round(minutes * 3))}초쯤" if minutes else ""
        if self.translate_check.isChecked():
            guess += ", 번역까지 하면 몇 분 더" if guess else "몇 분"
        if guess:
            self._note(f"영상 {minutes:.1f}분 — {guess} 걸립니다")

        def done(draft):
            self.model.replace(draft.events, getattr(draft, "sources", None) or None)
            self.waveform.set_events(self.model.events)
            self._preview_timer.start()
            notes = len(draft.notes)

            # **대조 결과를 말한다.** `align.summary()`가 이미 세어 놓는데 화면에
            # 나오지 않고 있었다. 대본이 일부 빠지는 일이 흔하므로(사용자 확인
            # 2026-08-12) **무엇이 빠져 있었나가 곧 손볼 목록**이다.
            st = getattr(draft, "stats", None) or {}
            if st.get("from_transcript") or st.get("no_audio"):
                parts = []
                if st.get("from_script"):
                    parts.append(f"대본에서 {st['from_script']}개")
                if st.get("from_transcript"):
                    parts.append(f"대본에 없어 전사로 채운 것 {st['from_transcript']}개")
                if st.get("no_audio"):
                    parts.append(f"대본에 있는데 소리가 없는 것 {st['no_audio']}개")
                self._note("대조 결과 — " + ", ".join(parts))

            self.statusBar().showMessage(
                f"자막 {len(draft.events)}개를 만들었습니다"
                + (f" — 봐야 할 자리 {notes}곳" if notes else ""))
            if draft.notes:
                self._show_violations([
                    {"event_index": i, "rule_id": "확인", "detail": note,
                     "auto_fixable": False} for i, note in draft.notes])

        self._start(job, done, "영상에서 자막을 만드는 중입니다...")

    def _stage_guard(self, stage_id: str) -> bool:
        """단계를 켤 수 있는지 묻고, 안 되면 **왜인지** 화면에 보인다.

        이유를 여기서 만들지 않는다 — `pipeline.STAGES`가 갖고 있다. 전에는 같은
        안내 문구가 이 파일 세 곳에 복사돼 있었다.
        """
        from checker.pipeline import stage_by_id

        stage = stage_by_id(stage_id)
        if stage is None:
            return True
        ok, why = stage.available(has_subtitle=bool(self.model.events),
                                  has_video=bool(getattr(self, "_video_path", None)))
        if not ok:
            self._refuse(f"[{stage.label}]를 지금 할 수 없습니다", why)
        return ok

    def _refresh_stages(self) -> None:
        """버튼의 켬/끔과 안내를 상태에 맞춘다. 자막·영상이 바뀔 때마다 부른다."""
        from checker.pipeline import STAGES

        for stage in STAGES:
            action = self.stage_actions.get(stage.id)
            if action is None:
                continue
            ok, why = stage.available(has_subtitle=bool(self.model.events),
                                      has_video=bool(getattr(self, "_video_path", None)))
            action.setEnabled(ok)
            # 끈 이유를 도구설명으로 보인다. 눌러 보고 팝업으로 알게 되는 것보다 낫다.
            action.setToolTip(stage.note if ok else f"{why}\n\n{stage.note}")

    def _apply_stage_result(self, events, violations, label: str) -> None:
        """단계 결과를 화면에 반영한다. 세 단계가 같은 뒷처리를 한다."""
        self.model.replace(events)
        self.waveform.set_events(self.model.events)
        self._preview_timer.start()
        self._show_violations(violations)
        self.statusBar().showMessage(f"{label} — 남은 지적 {len(violations)}건")
        self._refresh_stages()

    def run_korean(self) -> None:
        """② 한국어 교정. **규정 검사와 갈라 놓았다** — 전에는 한 버튼이 둘을 했고,
        어느 쪽이 언제 걸리는지 화면만 봐서는 알 수 없었다."""
        self._note("[② 한국어 교정] 눌림")
        if not self._stage_guard("korean"):
            return
        path = self._corrector_path()
        if not path:
            self._refuse("한국어 교정기를 찾지 못했습니다",
                         "교정기 폴더를 프로그램 옆에 두거나 [도움말 → 진단]에서 자리를 "
                         "확인하세요.")
            return
        job = jobs.CheckJob(self.model.events, self._profile(), fix=False,
                            korean=True, corrector_path=path)
        self._start(job,
                    lambda r: self._apply_stage_result(r[0], r[1], "한국어 교정 완료"),
                    "한국어 교정 중입니다...")

    def run_check(self) -> None:
        """③ 규정 검사. 발주처 규정만 본다. 한국어 교정은 ②가 한다."""
        self._note("[③ 규정 검사] 눌림")
        if not self._stage_guard("check"):
            return
        job = jobs.CheckJob(self.model.events, self._profile(), fix=True,
                            korean=False, corrector_path=None)
        self._start(job,
                    lambda r: self._apply_stage_result(r[0], r[1], "규정 검사 완료"),
                    "규정 검사 중입니다...")

    def run_translate(self) -> None:
        self._note("[번역] 눌림")
        if not self._stage_guard("translate"):
            return
        from checker.knp import find_for
        knp = find_for(self.subtitle_path) if self.subtitle_path else None
        # **번역 전 글자가 원어다.** 지금 잡아 두지 않으면 되돌릴 수도, 견줄 수도 없다.
        sources = self.model.remember_sources()
        job = jobs.TranslateJob(self.model.events, self._profile(),
                                passes=3 if self.translate_check.isChecked() else 1,
                                knp=knp)

        def done(events):
            self.model.replace(events, sources)
            self.waveform.set_events(self.model.events)
            self._preview_timer.start()
            self.statusBar().showMessage(
                f"번역했습니다 — 타임코드는 그대로입니다({len(events)}개)")

        self._start(job, done, "한국어로 옮기는 중입니다...")

    def run_terms(self) -> None:
        self._note("[용어표] 눌림")
        if not self._stage_guard("terms"):
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
                ("원어 대본 열기...", "Ctrl+Alt+O", self.open_script),
                ("자막 저장", "Ctrl+S", self.save_subtitle),
        ):
            action = QAction(title, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            file_menu.addAction(action)

        view_menu = self.menuBar().addMenu("보기(&V)")
        # **작업마다 크게 봐야 하는 곳이 다르다.** 타임코드를 잡을 때는 파형이,
        # 번역을 다듬을 때는 표가 커야 한다. 매번 끌게 하지 않고 한 번에 바꾼다.
        for title, shortcut, layout in (
                ("타임코드 작업 (파형 크게)", "Ctrl+1", "spotting"),
                ("번역 작업 (표 크게)", "Ctrl+2", "translating"),
                ("영상 크게", "Ctrl+3", "video"),
                ("고르게", "Ctrl+0", "balanced"),
        ):
            action = QAction(title, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(lambda _=False, name=layout: self.apply_layout(name))
            view_menu.addAction(action)

        help_menu = self.menuBar().addMenu("도움말(&H)")
        diagnosis = QAction("진단...", self)
        diagnosis.triggered.connect(self.show_diagnosis)
        help_menu.addAction(diagnosis)
        shortcuts = QAction("단축키...", self)
        shortcuts.setShortcut(QKeySequence("F1"))
        shortcuts.triggered.connect(self.show_shortcuts)
        help_menu.addAction(shortcuts)

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
        self._refresh_stages()
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
        self._refresh_stages()
        self.waveform.set_events(self.model.events)
        self._preview_timer.start()
        self.statusBar().showMessage(f"자막 {len(events)}개: {self.subtitle_path.name}")

    def open_script(self) -> None:
        """원어 대본을 원어 칸에 채운다.

        **대본은 자막 파일로 오지 않는다.** 워드·텍스트·PDF로 온다. 자막 형식만
        열 수 있으면 대본을 쓸 수 없다(사용자 지적 2026-08-12).

        자막이 이미 있으면 순서대로 짝지어 원어 칸에 넣는다. 수가 다르면 **맞는
        데까지만** 넣고 얼마나 어긋났는지 말한다 — 조용히 밀어 넣으면 엉뚱한 대사가
        엉뚱한 자막에 붙는다.
        """
        from checker.script import ScriptUnavailable, file_filter, read_lines

        path, _ = QFileDialog.getOpenFileName(self, "원어 대본 열기", "", file_filter())
        if not path:
            return
        try:
            lines = read_lines(Path(path))
        except ScriptUnavailable as exc:
            QMessageBox.warning(self, "대본을 읽지 못했습니다", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "대본을 읽지 못했습니다", f"{type(exc).__name__}: {exc}")
            return

        if not lines:
            QMessageBox.warning(self, "대본이 비어 있습니다", Path(path).name)
            return

        self._script_lines = lines
        if not self.model.events:
            self._note(f"대본 {len(lines)}줄을 읽었습니다. "
                       "영상을 열고 [영상에서 자막 만들기]를 누르면 대조합니다")
            return

        sources = {event.index: (lines[i].text if i < len(lines) else "")
                   for i, event in enumerate(self.model.events)}
        self.model.replace(self.model.events, sources)
        message = f"대본 {len(lines)}줄을 원어 칸에 넣었습니다"
        if len(lines) != len(self.model.events):
            message += (f" — 자막은 {len(self.model.events)}개입니다. "
                        "수가 달라 뒤로 갈수록 어긋납니다")
        self._note(message)

    def save_subtitle(self) -> None:
        if not self.model.events:
            return
        # **원본을 덮어쓰지 않는다.** 어디에 저장할지 사람이 정한다.
        suffix = getattr(self, "_prefs", {}).get("save_suffix", ".edited")
        suggested = str(self.subtitle_path.with_suffix(f"{suffix}.srt")) \
            if self.subtitle_path else "자막.srt"
        path, _ = QFileDialog.getSaveFileName(self, "자막 저장", suggested, SUBTITLE_FILTER)
        if not path:
            return
        write_srt(self.model.events, Path(path))
        message = f"저장했습니다: {path}"

        # **원어가 있으면 함께 낸다.** 자막은 두 벌이고, 검수자가 원어를 본다.
        if self.model.sources and getattr(self, "_prefs", {}).get("save_source_too", True):
            from checker.model import Event
            source_path = Path(path).with_suffix(".원어.srt")
            write_srt([Event(e.index, e.start_ms, e.end_ms,
                             self.model.sources.get(e.index, ""))
                       for e in self.model.events
                       if self.model.sources.get(e.index)], source_path)
            message += f"  /  원어: {source_path.name}"
        self.statusBar().showMessage(message)

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

    # --- 단축키 -------------------------------------------------------
    #
    # 목록과 설명은 `app/shortcuts.py`에 있다. **설명이 키보다 중요하다** —
    # 무엇을 할 수 있는지 알아야 도구를 쓴다(사용자 지적 2026-08-12).
    def _build_shortcuts(self) -> None:
        from . import shortcuts

        self._shortcut_actions = {}
        keys = shortcuts.load()
        for action in shortcuts.ACTIONS:
            item = QAction(action.title, self)
            item.setShortcut(QKeySequence(keys.get(action.key, action.default)))
            item.setToolTip(action.what)
            item.triggered.connect(getattr(self, action.slot))
            self.addAction(item)
            self._shortcut_actions[action.key] = item

    def reload_shortcuts(self) -> None:
        """바꾼 단축키를 곧바로 반영한다. 프로그램을 다시 켜게 하지 않는다."""
        from . import shortcuts

        keys = shortcuts.load()
        for name, item in self._shortcut_actions.items():
            item.setShortcut(QKeySequence(keys.get(name, "")))

    def _current_event(self):
        row = self.table.currentIndex().row()
        return self.model.event_at(row)

    def _apply_edit(self, events, focus_index: int) -> None:
        """고친 결과를 표·파형·미리 보기에 한 번에 반영한다."""
        self.model.replace(events)
        self.waveform.set_events(self.model.events)
        self._preview_timer.start()
        for row, event in enumerate(self.model.events):
            if event.index == focus_index:
                self.table.selectRow(row)
                break

    def step_back(self) -> None:
        self.step(-1)

    def step_forward(self) -> None:
        self.step(1)

    def zoom_in(self) -> None:
        self.waveform.zoom(0.7)

    def zoom_out(self) -> None:
        self.waveform.zoom(1.4)

    def go_previous(self) -> None:
        self._go(-1)

    def go_next(self) -> None:
        self._go(1)

    def _go(self, step: int) -> None:
        row = self.table.currentIndex().row()
        row = max(0, min(len(self.model.events) - 1, (row if row >= 0 else 0) + step))
        self.table.selectRow(row)
        event = self.model.event_at(row)
        if event and self.player:
            self.player.seek(event.start_ms)

    def go_to_number(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        number, ok = QInputDialog.getInt(self, "자막 번호로 이동", "번호",
                                         1, 1, max(1, len(self.model.events)))
        if not ok:
            return
        for row, event in enumerate(self.model.events):
            if event.index == number:
                self.table.selectRow(row)
                if self.player:
                    self.player.seek(event.start_ms)
                break

    def split_cue(self) -> None:
        from .edits import split_at
        event = self._current_event()
        if not event or not self.player:
            return
        events, new_index = split_at(self.model.events, event.index,
                                     self.player.position_ms)
        self._apply_edit(events, new_index)
        self._note(f"#{event.index}를 나눴습니다")

    def merge_cue(self) -> None:
        self._merge(dialogue=False)

    def merge_dialogue(self) -> None:
        self._merge(dialogue=True)

    def _merge(self, dialogue: bool) -> None:
        from .edits import merge_with_next
        event = self._current_event()
        if not event:
            return
        events, index = merge_with_next(self.model.events, event.index, dialogue)
        self._apply_edit(events, index)
        self._note(f"#{event.index}를 다음 자막과 합쳤습니다"
                   + (" (대화)" if dialogue else ""))

    def toggle_dash(self) -> None:
        from .edits import toggle_dash
        event = self._current_event()
        if event:
            event.text = toggle_dash(event)
            self._apply_edit(self.model.events, event.index)

    def remove_breaks(self) -> None:
        from .edits import remove_line_breaks
        event = self._current_event()
        if event:
            event.text = remove_line_breaks(event)
            self._apply_edit(self.model.events, event.index)

    def place_top(self) -> None:
        self._place("top_center")

    def place_bottom(self) -> None:
        self._place("default")

    def _place(self, place: str) -> None:
        from .edits import set_position
        event = self._current_event()
        if event:
            event.text = set_position(event, place)
            self._apply_edit(self.model.events, event.index)

    def set_in_point(self) -> None:
        self._set_point(start=True)

    def set_out_point(self) -> None:
        self._set_point(start=False)

    def _set_point(self, start: bool) -> None:
        from .edits import set_in_point, set_out_point
        event = self._current_event()
        if not event or not self.player:
            return
        at = self.player.position_ms
        done = (set_in_point if start else set_out_point)(
            self.model.events, event.index, at)
        if done:
            self._apply_edit(self.model.events, event.index)
            self._note(f"#{event.index} {'인점' if start else '아웃점'}을 "
                       f"{to_timecode(at)}로")
        else:
            self._note("이웃 자막을 침범하거나 자막이 뒤집혀서 하지 않았습니다")

    def show_shortcuts(self) -> None:
        """무엇을 할 수 있는지 **설명과 함께** 보여 준다. 바꾸려면 작업 기준 창으로."""
        from . import shortcuts

        keys = shortcuts.load()
        lines = []
        for group in shortcuts.GROUPS:
            lines.append(f"[{group}]")
            for action in shortcuts.ACTIONS:
                if action.group != group:
                    continue
                lines.append(f"  {keys.get(action.key, action.default):18} "
                             f"{action.title}")
                lines.append(f"  {'':18} {action.what}")
            lines.append("")
        box = QMessageBox(self)
        box.setWindowTitle("기능과 단축키")
        box.setText("<pre>" + "\n".join(lines).replace("<", "&lt;") + "</pre>")
        box.setInformativeText("바꾸려면 [작업 기준...] 창의 '단축키' 탭에서 고칩니다.")
        box.exec()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            self.toggle_play()
        else:
            super().keyPressEvent(event)

    def _jump_to_row(self, index) -> None:
        event = self.model.event_at(index.row())
        if event and self.player:
            self.player.seek(event.start_ms)

    def _sync_position(self) -> None:
        if not self.player:
            return
        # **창을 닫는 순간 mpv가 먼저 죽는다.** 그런데 이 시계는 계속 울려서
        # 죽은 mpv에 위치를 묻는다(2026-08-12 로그: ShutdownError). 사용자에게는
        # 프로그램이 마지막에 터지는 것으로 보인다.
        if getattr(self.player, "closed", False):
            self._follow.stop()
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

    LAYOUTS = {
        # (위:파형) 세로 비율 , (영상:표) 가로 비율
        "spotting": ((3, 7), (6, 4)),      # 파형을 아래 전체로 크게
        "translating": ((7, 3), (3, 7)),   # 표를 크게, 파형은 얇게
        "video": ((7, 3), (8, 2)),
        "balanced": ((6, 4), (5, 5)),
    }

    def apply_layout(self, name: str) -> None:
        """면적을 한 번에 바꾼다. 비율로 잡아 창 크기와 무관하게 같은 모양이 된다."""
        vertical, horizontal = self.LAYOUTS.get(name, self.LAYOUTS["balanced"])
        height = max(self.main_splitter.height(), 600)
        width = max(self.top_splitter.width(), 800)
        self.main_splitter.setSizes([int(height * vertical[0] / 10),
                                     int(height * vertical[1] / 10)])
        self.top_splitter.setSizes([int(width * horizontal[0] / 10),
                                    int(width * horizontal[1] / 10)])
        self._note(f"배치: {name}")

    def _settings(self):
        from PySide6.QtCore import QSettings
        return QSettings("자막생성기", "layout")

    def _restore_layout(self) -> None:
        """지난번 나눠 놓은 면적을 되살린다. 매번 다시 잡게 하지 않는다."""
        store = self._settings()
        for key, widget in (("main2", self.main_splitter), ("top", self.top_splitter)):
            state = store.value(f"splitter/{key}")
            if state is not None:
                widget.restoreState(state)
        geometry = store.value("window")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def closeEvent(self, event) -> None:
        if not self._restore:          # 시험용 창은 설정을 건드리지 않는다
            if self.player:
                self.player.close()
            super().closeEvent(event)
            return
        store = self._settings()
        store.setValue("splitter/main2", self.main_splitter.saveState())
        store.setValue("splitter/top", self.top_splitter.saveState())
        store.setValue("window", self.saveGeometry())
        if self.player:
            self.player.close()
        super().closeEvent(event)
