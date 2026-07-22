from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from autocamtracker.ui_qt.panels.base import FormPanel


class PlaybackPanel(FormPanel):
    startRequested = Signal()
    pauseRequested = Signal()
    stopRequested = Signal()
    recordRequested = Signal()
    speedChanged = Signal(float)
    loopChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(130)
        buttons = QWidget()
        grid = QGridLayout(buttons)
        grid.setContentsMargins(0, 0, 0, 0)
        for index, (label, signal) in enumerate(
            (
                ("Start", self.startRequested),
                ("Pause", self.pauseRequested),
                ("Stop", self.stopRequested),
                ("Record", self.recordRequested),
            )
        ):
            button = QPushButton(label)
            button.clicked.connect(signal)
            grid.addWidget(button, index // 3, index % 3)
        self.loop_button = QPushButton("Loop")
        self.loop_button.setCheckable(True)
        self.loop_button.setToolTip("Repeat the video file when it reaches the end")
        self.loop_button.toggled.connect(self.loopChanged)
        grid.addWidget(self.loop_button, 1, 1, 1, 2)
        self.speed = QComboBox()
        self.speed.addItems(["0.5×", "1×", "2×"])
        self.speed.setCurrentText("1×")
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timecode = QLabel("00:00:00:00 / 00:00:00:00")
        self.timecode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._timeline_fps = 0.0
        self._timeline_maximum = 0
        self.form.addRow(buttons)
        self.form.addRow("Speed", self.speed)
        self.form.addRow("Timeline", self.timeline)
        self.form.addRow("", self.timecode)
        self.speed.currentTextChanged.connect(self._emit_speed)
        self.timeline.valueChanged.connect(self._update_timecode_from_slider)

    def set_timeline(self, maximum: int, value: int, fps: float) -> None:
        self._timeline_maximum = max(0, int(maximum))
        self._timeline_fps = max(0.0, float(fps))
        if not self.timeline.isSliderDown():
            self.timeline.setRange(0, self._timeline_maximum)
            self.timeline.setValue(max(0, min(int(value), self._timeline_maximum)))
        self._update_timecode_from_slider(self.timeline.value())

    def _emit_speed(self, text: str) -> None:
        try:
            speed = float(text.replace("×", "").replace("x", ""))
        except ValueError:
            speed = 1.0
        self.speedChanged.emit(speed)

    def _update_timecode_from_slider(self, frame_index: int) -> None:
        self.timecode.setText(
            f"{format_timecode(frame_index, self._timeline_fps)} / "
            f"{format_timecode(self._timeline_maximum, self._timeline_fps)}"
        )


def format_timecode(frame_index: int, fps: float) -> str:
    if fps <= 0.0:
        return f"FRAME {max(0, int(frame_index))}"
    frame = max(0, int(frame_index))
    nominal_fps = max(1, int(round(fps)))
    elapsed = frame / fps
    whole_seconds = int(elapsed)
    frame_in_second = min(
        nominal_fps - 1, int((elapsed - whole_seconds) * nominal_fps)
    )
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frame_in_second:02d}"
