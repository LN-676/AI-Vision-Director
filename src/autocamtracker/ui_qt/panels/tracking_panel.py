from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QHBoxLayout, QPushButton, QWidget

from autocamtracker.ui_qt.panels.base import FormPanel


class TrackingPanel(FormPanel):
    autoTrackRequested = Signal()
    clearRequested = Signal()
    resetRequested = Signal()
    framingChanged = Signal(str)
    configurationChanged = Signal(str, str, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.profile = QComboBox()
        self.profile.addItems(["High FPS", "Balanced ID"])
        self.tracker = QComboBox()
        self.tracker.addItems(["ByteTrack", "BoT-SORT"])
        self.framing = QComboBox()
        self.framing.addItems(["wide", "medium", "close"])
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(0.05, 1.0)
        self.confidence.setSingleStep(0.05)
        self.confidence.setValue(0.25)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        for label, signal in (
            ("Auto Track", self.autoTrackRequested),
            ("Clear", self.clearRequested),
            ("Reset", self.resetRequested),
        ):
            button = QPushButton(label)
            button.clicked.connect(signal)
            row.addWidget(button)
        self.form.addRow("Profile", self.profile)
        self.form.addRow("Tracker", self.tracker)
        self.form.addRow("Framing", self.framing)
        self.form.addRow("Confidence", self.confidence)
        self.form.addRow(buttons)
        self.framing.currentTextChanged.connect(self.framingChanged)
        self.profile.currentTextChanged.connect(self._emit_configuration)
        self.tracker.currentTextChanged.connect(self._emit_configuration)
        self.confidence.valueChanged.connect(self._emit_configuration)

    def _emit_configuration(self, _value=None) -> None:
        self.configurationChanged.emit(
            self.profile.currentText(), self.tracker.currentText(), self.confidence.value()
        )
