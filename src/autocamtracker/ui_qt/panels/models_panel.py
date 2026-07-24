"""Independent Detection and ReID model management page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, QUrl, Signal
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
LINKED_DETECTION_KEY = "models/linkedDetection"
LINKED_REID_KEY = "models/linkedReid"
SELECTED_DETECTION_KEY = "models/selectedDetection"
SELECTED_REID_KEY = "models/selectedReid"


class ModelsPanel(QWidget):
    detectorModelChanged = Signal(str)
    reidModelChanged = Signal(str)
    modelsChanged = Signal()

    def __init__(
        self,
        model_dir: Path,
        default_model: str,
        default_reid_model: str,
        settings: QSettings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.model_dir = Path(model_dir)
        self.default_model = str(self.model_dir / default_model)
        self.default_reid_model = str(self.model_dir / default_reid_model)
        self.settings = settings
        self.linked_detector_paths = set(
            self._stored_paths(LINKED_DETECTION_KEY)
        )
        self.linked_reid_paths = set(self._stored_paths(LINKED_REID_KEY))
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
            self._detector_selection_changed
        )
        self.reid_model.currentIndexChanged.connect(
            self._reid_selection_changed
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
        current_detector = str(
            self.detector_model.currentData()
            or self._stored_value(SELECTED_DETECTION_KEY)
            or self.default_model
        )
        current_reid = str(
            self.reid_model.currentData()
            or self._stored_value(SELECTED_REID_KEY)
            or self.default_reid_model
        )
        detector_paths = {
            path
            for path in self.model_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in DETECTION_MODEL_SUFFIXES
            and "-reid" not in path.stem.lower()
        }
        detector_paths.update(
            path for path in self.linked_detector_paths if path.is_file()
        )
        reid_paths = {
            path
            for path in self.model_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in REID_MODEL_SUFFIXES
            and "-reid" in path.stem.lower()
        }
        reid_paths.update(path for path in self.linked_reid_paths if path.is_file())
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
            self.link_detector_path(Path(path))

    def choose_reid_model(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Link ReID Model",
            str(self.model_dir),
            "ReID models (*.onnx)",
        )
        if path:
            self.link_reid_path(Path(path))

    def link_detector_path(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        if resolved.suffix.lower() not in DETECTION_MODEL_SUFFIXES:
            raise ValueError("Detection models must use .pt or .onnx")
        self.linked_detector_paths.add(resolved)
        self._save_paths(LINKED_DETECTION_KEY, self.linked_detector_paths)
        self._select_external(self.detector_model, resolved)
        self.detectorModelChanged.emit(str(resolved))
        self.modelsChanged.emit()

    def link_reid_path(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        if resolved.suffix.lower() not in REID_MODEL_SUFFIXES:
            raise ValueError("ReID models must use .onnx")
        self.linked_reid_paths.add(resolved)
        self._save_paths(LINKED_REID_KEY, self.linked_reid_paths)
        self._select_external(self.reid_model, resolved)
        self.reidModelChanged.emit(str(resolved))
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

    def reid_model_paths(self) -> list[Path]:
        return [
            Path(str(self.reid_model.itemData(index)))
            for index in range(self.reid_model.count())
            if self.reid_model.itemData(index)
        ]

    def _populate(
        self, combo: QComboBox, paths, selected_path: str
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        for path in sorted(paths):
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

    def _detector_selection_changed(self, _index: int) -> None:
        path = str(self.detector_model.currentData() or "")
        self._save_value(SELECTED_DETECTION_KEY, path)
        self.detectorModelChanged.emit(path)

    def _reid_selection_changed(self, _index: int) -> None:
        path = str(self.reid_model.currentData() or "")
        self._save_value(SELECTED_REID_KEY, path)
        self.reidModelChanged.emit(path)

    def _stored_paths(self, key: str) -> list[Path]:
        if self.settings is None:
            return []
        value = self.settings.value(key, [])
        values = [value] if isinstance(value, str) else list(value or [])
        return [Path(str(item)) for item in values if Path(str(item)).is_file()]

    def _stored_value(self, key: str) -> str:
        return str(self.settings.value(key, "")) if self.settings is not None else ""

    def _save_paths(self, key: str, paths) -> None:
        if self.settings is not None:
            self.settings.setValue(key, [str(path) for path in sorted(paths)])
            self.settings.sync()

    def _save_value(self, key: str, value: str) -> None:
        if self.settings is not None:
            self.settings.setValue(key, value)
            self.settings.sync()
