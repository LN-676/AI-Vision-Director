from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QHBoxLayout, QPushButton, QWidget

from autocamtracker.ui_qt.panels.base import FormPanel


class TrackingPanel(FormPanel):
    autoTrackRequested = Signal()
    clearRequested = Signal()
    resetRequested = Signal()
    framingChanged = Signal(str)
    configurationChanged = Signal(str, str, float)
    detectorModelChanged = Signal(str)
    reidModelChanged = Signal(str)

    def __init__(
        self,
        model_dir: Path,
        default_model: str,
        default_reid_model: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.model_dir = Path(model_dir)
        self.default_model = default_model
        self.default_reid_model = default_reid_model
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
        self.detector_model = QComboBox()
        self.reid_model = QComboBox()
        refresh_models = QPushButton("Refresh Models")
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
        self.form.addRow("Detection model", self.detector_model)
        self.form.addRow("ReID model", self.reid_model)
        self.form.addRow(refresh_models)
        self.form.addRow("Tracker", self.tracker)
        self.form.addRow("Framing", self.framing)
        self.form.addRow("Confidence", self.confidence)
        self.form.addRow(buttons)
        self.framing.currentTextChanged.connect(self.framingChanged)
        self.profile.currentTextChanged.connect(self._emit_configuration)
        self.tracker.currentTextChanged.connect(self._emit_configuration)
        self.confidence.valueChanged.connect(self._emit_configuration)
        self.detector_model.currentIndexChanged.connect(
            lambda _index: self.detectorModelChanged.emit(
                str(self.detector_model.currentData() or "")
            )
        )
        self.reid_model.currentIndexChanged.connect(
            lambda _index: self.reidModelChanged.emit(
                str(self.reid_model.currentData() or "")
            )
        )
        refresh_models.clicked.connect(self.refresh_models)
        self.refresh_models()

    def _emit_configuration(self, _value=None) -> None:
        self.configurationChanged.emit(
            self.profile.currentText(), self.tracker.currentText(), self.confidence.value()
        )

    def refresh_models(self) -> None:
        current_detector = str(self.detector_model.currentData() or "")
        current_reid = str(self.reid_model.currentData() or "")
        detector_paths = sorted(self.model_dir.rglob("*.pt"))
        reid_paths = sorted(self.model_dir.rglob("*-reid.onnx"))
        self._populate_models(
            self.detector_model,
            detector_paths,
            current_detector or str(self.model_dir / self.default_model),
        )
        self._populate_models(
            self.reid_model,
            reid_paths,
            current_reid or str(self.model_dir / self.default_reid_model),
        )

    def _populate_models(
        self, combo: QComboBox, paths: list[Path], selected_path: str
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        for path in paths:
            try:
                label = str(path.relative_to(self.model_dir))
            except ValueError:
                label = path.name
            combo.addItem(label, str(path))
        selected_index = combo.findData(selected_path)
        combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        combo.blockSignals(False)
