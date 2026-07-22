from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class VehicleDatabasePanel(QWidget):
    addRequested = Signal()
    linkRequested = Signal(int)
    findRequested = Signal(int)
    releaseRequested = Signal()
    deleteRequested = Signal(int)
    previewRequested = Signal(int)
    manageFeaturesRequested = Signal(int)
    manualFeatureRequested = Signal()
    autoFeatureRequested = Signal()
    findThresholdChanged = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["GID", "Class", "LID", "Features"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMouseTracking(True)
        self.table.viewport().setMouseTracking(True)
        self.table.viewport().installEventFilter(self)
        self.table.cellEntered.connect(self._request_preview)
        self.table.cellDoubleClicked.connect(self._open_feature_manager)
        self._preview = QLabel(None, Qt.WindowType.ToolTip)
        self._vehicle_signature: tuple[tuple[object, ...], ...] = ()
        self._preview.setStyleSheet(
            "QLabel { background: #11151d; color: white; border: 1px solid #667085; "
            "padding: 6px; }"
        )
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        for label, callback in (
            ("Add", lambda: self.addRequested.emit()),
            ("Link", lambda: self._emit_selected(self.linkRequested)),
            ("Find", lambda: self._emit_selected(self.findRequested)),
            ("Release", lambda: self.releaseRequested.emit()),
            ("Delete", lambda: self._emit_selected(self.deleteRequested)),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout = QVBoxLayout(self)
        self.hint = QLabel("Double-click a vehicle to open its photo gallery.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #98a2b3;")
        layout.addWidget(self.hint)
        layout.addWidget(self.table)
        layout.addWidget(buttons)
        feature_controls = QWidget()
        feature_form = QFormLayout(feature_controls)
        feature_form.setContentsMargins(0, 0, 0, 0)
        self.find_threshold = QDoubleSpinBox()
        self.find_threshold.setRange(0.0, 1.0)
        self.find_threshold.setSingleStep(0.05)
        self.find_threshold.setValue(0.75)
        feature_buttons = QWidget()
        feature_row = QHBoxLayout(feature_buttons)
        feature_row.setContentsMargins(0, 0, 0, 0)
        self.manual_feature_button = QPushButton("Add Manual Feature")
        self.auto_feature_button = QPushButton("Start / Stop Auto Feature")
        feature_row.addWidget(self.manual_feature_button)
        feature_row.addWidget(self.auto_feature_button)
        feature_form.addRow("Find GID confidence threshold", self.find_threshold)
        feature_form.addRow(feature_buttons)
        layout.addWidget(feature_controls)
        self.find_threshold.valueChanged.connect(self.findThresholdChanged)
        self.manual_feature_button.clicked.connect(self.manualFeatureRequested)
        self.auto_feature_button.clicked.connect(self.autoFeatureRequested)

    def selected_gid(self) -> int | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return int(item.data(256)) if item is not None else None

    def _emit_selected(self, signal) -> None:
        gid = self.selected_gid()
        if gid is not None:
            signal.emit(gid)

    def set_vehicles(self, vehicles) -> None:
        signature = tuple(
            (
                vehicle.vehicle_id,
                vehicle.display_name,
                vehicle.class_name,
                vehicle.last_track_id,
                vehicle.master_feature_count,
            )
            for vehicle in vehicles
        )
        if signature == self._vehicle_signature:
            return
        selected_gid = self.selected_gid()
        self._vehicle_signature = signature
        self.table.setRowCount(len(vehicles))
        for row, vehicle in enumerate(vehicles):
            gid = QTableWidgetItem(str(vehicle.display_name))
            gid.setData(256, vehicle.vehicle_id)
            values = (
                gid,
                QTableWidgetItem(str(vehicle.class_name)),
                QTableWidgetItem(
                    str(vehicle.last_track_id)
                    if vehicle.last_track_id is not None
                    else "--"
                ),
                QTableWidgetItem(str(vehicle.master_feature_count)),
            )
            for column, item in enumerate(values):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
            if vehicle.vehicle_id == selected_gid:
                self.table.selectRow(row)

    def show_feature_preview(self, gid: int, crop_jpeg: bytes | None) -> None:
        if not crop_jpeg:
            self._preview.hide()
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(crop_jpeg):
            self._preview.hide()
            return
        self._preview.setPixmap(
            pixmap.scaled(
                240,
                160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._preview.setToolTip(f"GID {gid} first feature snapshot")
        self._preview.adjustSize()
        self._preview.move(QCursor.pos() + QPoint(16, 16))
        self._preview.show()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._preview.hide()
        super().leaveEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self.table.viewport() and event.type() == QEvent.Type.Leave:
            self._preview.hide()
        return super().eventFilter(watched, event)

    def _request_preview(self, row: int, _column: int) -> None:
        gid = self._gid_for_row(row)
        if gid is not None:
            self.previewRequested.emit(gid)

    def _open_feature_manager(self, row: int, _column: int) -> None:
        gid = self._gid_for_row(row)
        if gid is not None:
            self._preview.hide()
            self.manageFeaturesRequested.emit(gid)

    def _gid_for_row(self, row: int) -> int | None:
        item = self.table.item(row, 0) if row >= 0 else None
        return int(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None
