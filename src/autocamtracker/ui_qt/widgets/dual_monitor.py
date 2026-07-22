"""Stable central Before/After monitor pair for Scheme A."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from autocamtracker.ui_qt.widgets.video_view import VideoView


class DualMonitorWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.before_view = VideoView()
        self.after_view = VideoView()
        self.splitter.addWidget(self._monitor("Before · Detection", self.before_view))
        self.splitter.addWidget(self._monitor("After · Reframe", self.after_view))
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.splitter)

    @staticmethod
    def _monitor(title: str, view: VideoView) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(view)
        return group
