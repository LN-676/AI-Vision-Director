from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
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

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["GID", "Class", "LID", "Features"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
        layout.addWidget(self.table)
        layout.addWidget(buttons)

    def selected_gid(self) -> int | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return int(item.data(256)) if item is not None else None

    def _emit_selected(self, signal) -> None:
        gid = self.selected_gid()
        if gid is not None:
            signal.emit(gid)

    def set_vehicles(self, vehicles) -> None:
        self.table.setRowCount(len(vehicles))
        for row, vehicle in enumerate(vehicles):
            gid = QTableWidgetItem(str(vehicle.display_name))
            gid.setData(256, vehicle.vehicle_id)
            values = (
                gid,
                QTableWidgetItem(str(vehicle.class_name)),
                QTableWidgetItem(str(vehicle.last_track_id or "--")),
                QTableWidgetItem(str(vehicle.master_feature_count)),
            )
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
