"""Independent Detection and ReID model management page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


DETECTION_MODEL_SUFFIXES = (".pt", ".onnx")
REID_MODEL_SUFFIXES = (".onnx",)


class ModelsPanel(QWidget):
    detectorModelChanged = Signal(str)
    reidModelChanged = Signal(str)
    modelsChanged = Signal()

    def __init__(
        self,
        model_dir: Path,
        default_model: str,
        default_reid_model: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.model_dir = Path(model_dir)
        self.default_model = str(self.model_dir / default_model)
        self.default_reid_model = str(self.model_dir / default_reid_model)
        self.detector_model = QComboBox()
        self.reid_model = QComboBox()

        layout = QVBoxLayout(self)
        title = QLabel("Models")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Detection model"))
        layout.addWidget(self.detector_model)
        layout.addLayout(
            self._button_row(
                "Link Detection Model…",
                self.choose_detector_model,
            )
        )
        detection_hint = QLabel(
            "Supported Detection files: Ultralytics YOLO .pt and exported .onnx"
        )
        detection_hint.setWordWrap(True)
        layout.addWidget(detection_hint)

        layout.addSpacing(12)
        layout.addWidget(QLabel("ReID model"))
        layout.addWidget(self.reid_model)
        layout.addLayout(
            self._button_row(
                "Link ReID Model…",
                self.choose_reid_model,
            )
        )
        reid_hint = QLabel(
            "Supported ReID files: ONNX embedding models (.onnx). "
            "The embedding output must match the existing gallery model."
        )
        reid_hint.setWordWrap(True)
        layout.addWidget(reid_hint)

        layout.addSpacing(12)
        actions = QHBoxLayout()
        refresh = QPushButton("Refresh Models")
        reveal = QPushButton("Open Model Folder")
        refresh.clicked.connect(self.refresh_models)
        reveal.clicked.connect(self.open_model_folder)
        actions.addWidget(refresh)
        actions.addWidget(reveal)
        layout.addLayout(actions)
        layout.addStretch(1)

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
        self.refresh_models()

    def _button_row(self, label: str, callback) -> QHBoxLayout:
        row = QHBoxLayout()
        button = QPushButton(label)
        button.clicked.connect(callback)
        row.addWidget(button)
        row.addStretch(1)
        return row

    def refresh_models(self) -> None:
        current_detector = str(self.detector_model.currentData() or self.default_model)
        current_reid = str(self.reid_model.currentData() or self.default_reid_model)
        detector_paths = sorted(
            path
            for path in self.model_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in DETECTION_MODEL_SUFFIXES
            and "-reid" not in path.stem.lower()
        )
        reid_paths = sorted(
            path
            for path in self.model_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in REID_MODEL_SUFFIXES
            and "-reid" in path.stem.lower()
        )
        self._populate(self.detector_model, detector_paths, current_detector)
        self._populate(self.reid_model, reid_paths, current_reid)
        self.modelsChanged.emit()

    def choose_detector_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Link Detection Model",
            str(self.model_dir),
            "Detection models (*.pt *.onnx)",
        )
        if path:
            self._select_external(self.detector_model, Path(path))
            self.detectorModelChanged.emit(path)
            self.modelsChanged.emit()

    def choose_reid_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Link ReID Model",
            str(self.model_dir),
            "ReID models (*.onnx)",
        )
        if path:
            self._select_external(self.reid_model, Path(path))
            self.reidModelChanged.emit(path)
            self.modelsChanged.emit()

    def open_model_folder(self) -> None:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.model_dir.resolve())))

    def detection_model_paths(self) -> list[Path]:
        return [
            Path(str(self.detector_model.itemData(index)))
            for index in range(self.detector_model.count())
            if self.detector_model.itemData(index)
        ]

    def _populate(
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
        if selected_path and combo.findData(selected_path) < 0 and Path(selected_path).is_file():
            combo.addItem(f"{Path(selected_path).name} (linked)", selected_path)
        selected_index = combo.findData(selected_path)
        combo.setCurrentIndex(selected_index if selected_index >= 0 else 0)
        combo.blockSignals(False)

    @staticmethod
    def _select_external(combo: QComboBox, path: Path) -> None:
        value = str(path)
        index = combo.findData(value)
        if index < 0:
            combo.addItem(f"{path.name} (linked)", value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)
