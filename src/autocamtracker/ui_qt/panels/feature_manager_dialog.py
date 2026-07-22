"""Finder-style feature-gallery review and deletion dialog."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
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
        self.setWindowTitle(f"Feature Manager · GID {display_name}")
        self.setMinimumSize(520, 420)
        self.resize(920, 640)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.gallery.setFlow(QListWidget.Flow.LeftToRight)
        self.gallery.setWrapping(True)
        self.gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.gallery.setMovement(QListWidget.Movement.Static)
        self.gallery.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.gallery.setIconSize(QSize(180, 120))
        self.gallery.setGridSize(QSize(215, 180))
        self.gallery.setSpacing(6)
        self.gallery.setUniformItemSizes(True)
        self.delete_button = QPushButton("Delete Feature")
        self.delete_button.clicked.connect(self._delete_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.gallery, 1)
        layout.addWidget(self.delete_button)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        self.gallery.clear()
        snapshots = self.snapshot_provider(self.gid)
        self.summary.setText(
            f"GID {self.display_name} · Active master features: {len(snapshots)} · "
            "Click a photo to select it. Command/Ctrl-click selects multiple photos; "
            "Shift-click selects a range."
        )
        if not snapshots:
            self.gallery.setEnabled(False)
            return
        self.gallery.setEnabled(True)
        for snapshot in snapshots:
            icon = QIcon()
            if snapshot.crop_jpeg:
                pixmap = QPixmap()
                if pixmap.loadFromData(snapshot.crop_jpeg):
                    icon = QIcon(
                        pixmap.scaled(
                            self.gallery.iconSize(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            created = datetime.fromtimestamp(snapshot.created_at).strftime("%m-%d %H:%M:%S")
            item = QListWidgetItem(
                icon,
                f"Feature #{snapshot.feature_id} · Frame {snapshot.frame_index}\n"
                f"Quality {snapshot.quality_score:.2f} · {created}",
            )
            item.setData(Qt.ItemDataRole.UserRole, snapshot.feature_id)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setToolTip(
                f"Feature #{snapshot.feature_id}\nFrame {snapshot.frame_index}\n"
                f"Quality {snapshot.quality_score:.2f}\nCreated {created}"
            )
            self.gallery.addItem(item)

    def _delete_selected(self) -> None:
        selected = [
            int(item.data(Qt.ItemDataRole.UserRole))
            for item in self.gallery.selectedItems()
        ]
        if not selected:
            QMessageBox.information(self, "Feature Manager", "Select at least one photo first.")
            return
        answer = QMessageBox.question(
            self,
            "Delete Selected Features",
            f"Delete {len(selected)} selected feature photo(s) from active ReID matching? "
            "The audit record will be retained.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        deleted = self.rollback_callback(self.gid, selected)
        QMessageBox.information(
            self,
            "Feature Manager",
            f"Deleted {deleted} feature photo(s) from active ReID matching.",
        )
        self.refresh()
