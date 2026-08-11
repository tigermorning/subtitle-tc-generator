"""파형 — 여기서 타임코드를 잡는다.

**이것이 있어야 SE를 안 켠다.** 자막 작업의 절반은 "말이 어디서 시작하고 끝나는가"를
눈으로 확인하고 경계를 끄는 일이다. 표와 영상만으로는 그 일을 할 수 없다.

그리는 것:

    파형        소리의 크기. 말과 침묵이 눈에 보인다
    자막 구간   현재 자막들의 인·아웃. 가장자리를 끌어 옮긴다
    말소리 구간 VAD가 찾은 자리(연한 띠). 사람이 견주는 기준이 된다
    장면 전환   세로선. 자막이 걸치면 안 되는 자리다
    재생 위치   지금 어디를 보고 있는지

**소리는 8kHz로 읽는다.** 파형을 그리는 데는 그 이상이 필요 없고, 45분짜리도
40MB 안에 들어온다. 정확도가 필요한 곳(VAD·전사)은 따로 16kHz로 읽는다.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

BACKGROUND = QColor("#12141a")
WAVE = QColor("#5b8dd9")
CUE_FILL = QColor(90, 200, 140, 60)
CUE_EDGE = QColor("#4ec48a")
CUE_ACTIVE = QColor(255, 200, 90, 90)
SPEECH_BAND = QColor(120, 120, 200, 45)
SHOT_LINE = QColor("#d96b6b")
PLAYHEAD = QColor("#ffd166")
TEXT = QColor("#c8ccd4")

EDGE_GRAB_PX = 5          # 가장자리를 잡았다고 볼 거리
MIN_CUE_MS = 100          # 끌어서 이보다 짧게 만들 수 없다


class Waveform(QWidget):
    """파형 + 자막 구간 편집."""

    seek_requested = Signal(int)              # 사람이 그 자리로 가고 싶어 한다
    cue_changed = Signal(int, int, int)       # (자막 번호, 새 인점, 새 아웃점)
    cue_selected = Signal(int)                # 자막 번호

    def __init__(self, parent=None):
        super().__init__(parent)
        # 파형도 얇게 눌릴 수 있어야 한다. 번역을 다듬을 때는 표가 주인이다.
        self.setMinimumHeight(60)
        self.setMouseTracking(True)

        self.peaks: list[tuple[float, float]] = []   # 8kHz 기준 (최소, 최대)
        self.samples_per_peak = 256
        self.sample_rate = 8000
        self.duration_ms = 0

        self.events = []                 # checker.model.Event 목록(참조)
        self.speech: list[tuple[int, int]] = []
        self.shots: list[int] = []

        self.view_start_ms = 0
        self.ms_per_pixel = 20.0         # 20ms/px면 화면 하나에 약 20초
        self.position_ms = 0
        self.follow = True
        # 무엇을 그릴지는 설정이 정한다. 화면이 복잡하면 오히려 못 본다.
        self.show_speech = True
        self.show_shots = True

        self._drag: tuple[int, str] | None = None    # (자막 번호, 'start'|'end')

    # --- 자료 ---------------------------------------------------------
    def set_peaks(self, peaks, samples_per_peak: int, sample_rate: int,
                  duration_ms: int) -> None:
        self.peaks = peaks
        self.samples_per_peak = samples_per_peak
        self.sample_rate = sample_rate
        self.duration_ms = duration_ms
        self.update()

    def set_events(self, events) -> None:
        self.events = events
        self.update()

    def set_marks(self, speech=None, shots=None) -> None:
        if speech is not None:
            self.speech = speech
        if shots is not None:
            self.shots = shots
        self.update()

    def set_position(self, ms: int) -> None:
        self.position_ms = ms
        if self.follow:
            span = self.width() * self.ms_per_pixel
            # 가장자리에 닿을 때만 움직인다. 매 프레임 따라 움직이면 눈이 어지럽다.
            if not (self.view_start_ms + span * 0.15 <= ms
                    <= self.view_start_ms + span * 0.85):
                self.view_start_ms = max(0, int(ms - span * 0.3))
        self.update()

    def zoom(self, factor: float, anchor_ms: int | None = None) -> None:
        """확대·축소. 보고 있던 자리를 붙잡아 둔다."""
        anchor = self.position_ms if anchor_ms is None else anchor_ms
        offset = (anchor - self.view_start_ms) / max(self.ms_per_pixel, 0.001)
        self.ms_per_pixel = max(1.0, min(500.0, self.ms_per_pixel * factor))
        self.view_start_ms = max(0, int(anchor - offset * self.ms_per_pixel))
        self.update()

    # --- 좌표 ---------------------------------------------------------
    def ms_at(self, x: int) -> int:
        return int(self.view_start_ms + x * self.ms_per_pixel)

    def x_at(self, ms: int) -> int:
        return int((ms - self.view_start_ms) / max(self.ms_per_pixel, 0.001))

    # --- 그리기 -------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        width, height = self.width(), self.height()
        middle = height // 2
        view_end_ms = self.ms_at(width)

        # 말소리 구간을 바닥에 깐다 — 기준이지 결과가 아니다.
        for start, end in (self.speech if self.show_speech else []):
            if end < self.view_start_ms or start > view_end_ms:
                continue
            painter.fillRect(QRect(self.x_at(start), 0,
                                   max(1, self.x_at(end) - self.x_at(start)), height),
                             SPEECH_BAND)

        # 파형
        if self.peaks:
            painter.setPen(QPen(WAVE, 1))
            per_peak_ms = self.samples_per_peak * 1000 / self.sample_rate
            for x in range(width):
                start_index = int(self.ms_at(x) / per_peak_ms)
                end_index = int(self.ms_at(x + 1) / per_peak_ms)
                if start_index >= len(self.peaks):
                    break
                chunk = self.peaks[start_index:max(end_index, start_index + 1)]
                if not chunk:
                    continue
                low = min(c[0] for c in chunk)
                high = max(c[1] for c in chunk)
                painter.drawLine(x, middle - int(high * middle),
                                 x, middle - int(low * middle))

        # 장면 전환 — 자막이 걸치면 안 되는 자리
        painter.setPen(QPen(SHOT_LINE, 1, Qt.DashLine))
        for shot in (self.shots if self.show_shots else []):
            if self.view_start_ms <= shot <= view_end_ms:
                painter.drawLine(self.x_at(shot), 0, self.x_at(shot), height)

        # 자막 구간
        current = self._event_at(self.position_ms)
        for event in self.events:
            if event.end_ms < self.view_start_ms or event.start_ms > view_end_ms:
                continue
            left, right = self.x_at(event.start_ms), self.x_at(event.end_ms)
            box = QRect(left, height - 42, max(2, right - left), 40)
            painter.fillRect(box, CUE_ACTIVE if event is current else CUE_FILL)
            painter.setPen(QPen(CUE_EDGE, 2))
            painter.drawLine(left, height - 42, left, height)
            painter.drawLine(right, height - 42, right, height)
            if right - left > 40:
                painter.setPen(TEXT)
                painter.drawText(box.adjusted(4, 2, -4, -2),
                                 Qt.AlignLeft | Qt.TextWordWrap,
                                 event.text.replace("\n", " ")[:40])

        # 재생 위치
        painter.setPen(QPen(PLAYHEAD, 2))
        x = self.x_at(self.position_ms)
        painter.drawLine(x, 0, x, height)

    # --- 조작 ---------------------------------------------------------
    def _event_at(self, ms: int):
        for event in self.events:
            if event.start_ms <= ms < event.end_ms:
                return event
        return None

    def _edge_at(self, x: int) -> tuple[object, str] | None:
        """가장자리를 잡았는지. 잡을 수 있어야 끌 수 있다."""
        for event in self.events:
            if abs(self.x_at(event.start_ms) - x) <= EDGE_GRAB_PX:
                return event, "start"
            if abs(self.x_at(event.end_ms) - x) <= EDGE_GRAB_PX:
                return event, "end"
        return None

    def mousePressEvent(self, mouse) -> None:
        if mouse.button() != Qt.LeftButton:
            return
        x = int(mouse.position().x())
        grabbed = self._edge_at(x)
        if grabbed and mouse.position().y() > self.height() - 60:
            event, side = grabbed
            self._drag = (event.index, side)
            self.cue_selected.emit(event.index)
            return
        # 가장자리가 아니면 그 자리로 간다.
        self.seek_requested.emit(self.ms_at(x))

    def mouseMoveEvent(self, mouse) -> None:
        x = int(mouse.position().x())
        if self._drag is None:
            near = self._edge_at(x)
            self.setCursor(Qt.SizeHorCursor if near and
                           mouse.position().y() > self.height() - 60 else Qt.ArrowCursor)
            return

        index, side = self._drag
        event = next((e for e in self.events if e.index == index), None)
        if event is None:
            return
        ms = max(0, self.ms_at(x))
        if side == "start":
            event.start_ms = min(ms, event.end_ms - MIN_CUE_MS)
        else:
            event.end_ms = max(ms, event.start_ms + MIN_CUE_MS)
        self.update()

    def mouseReleaseEvent(self, _mouse) -> None:
        if self._drag is None:
            return
        index, _side = self._drag
        self._drag = None
        event = next((e for e in self.events if e.index == index), None)
        if event:
            # 끌기가 끝났을 때만 알린다. 끄는 도중에 표를 다시 그리면 버벅인다.
            self.cue_changed.emit(event.index, event.start_ms, event.end_ms)

    def wheelEvent(self, wheel) -> None:
        if wheel.modifiers() & Qt.ControlModifier:
            factor = 0.8 if wheel.angleDelta().y() > 0 else 1.25
            self.zoom(factor, self.ms_at(int(wheel.position().x())))
        else:
            self.view_start_ms = max(
                0, int(self.view_start_ms - wheel.angleDelta().y() * self.ms_per_pixel))
            self.follow = False
            self.update()
