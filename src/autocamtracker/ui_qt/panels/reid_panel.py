from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDoubleSpinBox, QPushButton

from autocamtracker.ui_qt.panels.base import FormPanel


class ReIDPanel(FormPanel):
    manualFeatureRequested = Signal()
    autoFeatureRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        threshold = QDoubleSpinBox()
        threshold.setRange(0.0, 1.0)
        threshold.setSingleStep(0.05)
        threshold.setValue(0.75)
        manual = QPushButton("Add Manual Feature")
        auto = QPushButton("Start / Stop Auto Feature")
        self.form.addRow("Find GID threshold", threshold)
        self.form.addRow(manual)
        self.form.addRow(auto)
        manual.clicked.connect(self.manualFeatureRequested)
        auto.clicked.connect(self.autoFeatureRequested)
