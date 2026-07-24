from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QLabel, QPushButton

from autocamtracker.ui_qt.panels.base import FormPanel


class TrackShotPanel(FormPanel):
    modeChanged = Signal(str)
    rearmRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mode = QComboBox()
        self.mode.addItems(["AI Tracking", "Fixed Cut", "In/Out Auto"])
        self.mode.setToolTip(
            "AI Tracking follows a selected target. Fixed Cut holds the camera. "
            "In/Out Auto starts in the entry zone and stops in the exit zone."
        )
        rearm = QPushButton("Rearm")
        self.form.addRow("Mode", self.mode)
        hint = QLabel(
            "AI Tracking: continuous follow · Fixed Cut: hold position · "
            "In/Out Auto: entry-to-exit shot"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #687386;")
        self.form.addRow(hint)
        self.form.addRow(rearm)
        self.mode.currentTextChanged.connect(self.modeChanged)
        rearm.clicked.connect(self.rearmRequested)
