from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QSlider, QWidget
from PySide6.QtCore import Qt

from autocamtracker.ui_qt.panels.base import FormPanel


class PlaybackPanel(FormPanel):
    startRequested = Signal()
    pauseRequested = Signal()
    stopRequested = Signal()
    recordRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(105)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        for label, signal in (
            ("Start", self.startRequested),
            ("Pause", self.pauseRequested),
            ("Stop", self.stopRequested),
            ("Record", self.recordRequested),
        ):
            button = QPushButton(label)
            button.clicked.connect(signal)
            row.addWidget(button)
        self.speed = QComboBox()
        self.speed.addItems(["0.5×", "1×", "2×"])
        self.speed.setCurrentText("1×")
        self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.form.addRow(buttons)
        self.form.addRow("Speed", self.speed)
        self.form.addRow("Timeline", self.timeline)
