from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QPushButton

from autocamtracker.ui_qt.panels.base import FormPanel


class TrackShotPanel(FormPanel):
    modeChanged = Signal(str)
    rearmRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.mode = QComboBox()
        self.mode.addItems(["AI Tracking", "Fixed Cut", "In/Out Auto", "Zone"])
        rearm = QPushButton("Rearm")
        self.form.addRow("Mode", self.mode)
        self.form.addRow(rearm)
        self.mode.currentTextChanged.connect(self.modeChanged)
        rearm.clicked.connect(self.rearmRequested)
