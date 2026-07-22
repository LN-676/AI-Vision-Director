"""Feature-gallery review and contamination rollback dialog."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class FeatureManagerDialog(QDialog):
    def __init__(
        self,
        gid: int,
        display_name: str,
        snapshot_provider,
        rollback_callback,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.gid = gid
        self.display_name = display_name
        self.snapshot_provider = snapshot_provider
        self.rollback_callback = rollback_callback
        self._checks: dict[int, QCheckBox] = {}
        self.setWindowTitle(f"Feature Manager · GID {display_name}")
        self.setMinimumSize(820, 600)

        self.summary = QLabel()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.content = QWidget()
        self.grid = QGridLayout(self.content)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.content)
        rollback = QPushButton("Rollback Selected Contaminated Photos")
        rollback.clicked.connect(self._rollback_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(rollback)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._checks.clear()
        snapshots = self.snapshot_provider(self.gid)
        self.summary.setText(
            f"GID {self.display_name} · Active master features: {len(snapshots)} · "
            "Select contaminated photos to remove them from ReID matching."
        )
        if not snapshots:
            self.grid.addWidget(QLabel("No active master feature photos."), 0, 0)
            return
        for index, snapshot in enumerate(snapshots):
            tile = QFrame()
            tile.setFrameShape(QFrame.Shape.StyledPanel)
            tile_layout = QVBoxLayout(tile)
            preview = QLabel("No preview")
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setFixedSize(180, 120)
            if snapshot.crop_jpeg:
                pixmap = QPixmap()
                if pixmap.loadFromData(snapshot.crop_jpeg):
                    preview.setPixmap(
                        pixmap.scaled(
                            preview.size(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            created = datetime.fromtimestamp(snapshot.created_at).strftime("%m-%d %H:%M:%S")
            details = QLabel(
                f"Feature #{snapshot.feature_id} · Frame {snapshot.frame_index}\n"
                f"Quality {snapshot.quality_score:.2f} · {created}"
            )
            details.setAlignment(Qt.AlignmentFlag.AlignCenter)
            check = QCheckBox("Mark as contaminated")
            self._checks[snapshot.feature_id] = check
            tile_layout.addWidget(preview)
            tile_layout.addWidget(details)
            tile_layout.addWidget(check)
            self.grid.addWidget(tile, index // 4, index % 4)

    def _rollback_selected(self) -> None:
        selected = [feature_id for feature_id, check in self._checks.items() if check.isChecked()]
        if not selected:
            QMessageBox.information(self, "Feature Manager", "Select at least one photo first.")
            return
        answer = QMessageBox.question(
            self,
            "Rollback Contaminated Photos",
            f"Remove {len(selected)} selected photo(s) from active ReID matching? "
            "The audit record will be retained.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        rolled_back = self.rollback_callback(self.gid, selected)
        QMessageBox.information(
            self,
            "Feature Manager",
            f"Rolled back {rolled_back} contaminated photo(s).",
        )
        self.refresh()
