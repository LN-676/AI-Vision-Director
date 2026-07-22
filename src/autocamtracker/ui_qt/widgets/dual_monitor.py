"""Stable central Before/After monitor pair for Scheme A."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from autocamtracker.ui_qt.widgets.video_view import VideoView


class DualMonitorWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setHandleWidth(12)
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

    def set_metrics(self, metrics: dict) -> None:
        live_fps = float(metrics.get("display_fps", 0.0))
        source_fps = float(metrics.get("source_fps", 0.0))
        frame_index = int(metrics.get("frame_index", 0))
        dropped = int(metrics.get("skipped_frames", 0))
        self.before_view.set_metrics_text(
            f"LIVE {live_fps:5.1f} FPS   SOURCE {source_fps:5.1f} FPS\n"
            f"FRAME {frame_index:07d}   DROPPED {dropped}"
        )
        self.after_view.set_metrics_text(
            f"E2E {float(metrics.get('end_to_end_ms', 0.0)):5.1f} ms   "
            f"INFER {float(metrics.get('inference_ms', 0.0)):5.1f} ms   "
            f"PIPE {float(metrics.get('pipeline_ms', 0.0)):5.1f} ms\n"
            f"RX {float(metrics.get('receive_ms', 0.0)):5.1f} ms   "
            f"DECODE {float(metrics.get('decode_ms', 0.0)):4.1f} ms   "
            f"SYNC {float(metrics.get('video_lag_ms', 0.0)):5.1f} ms"
        )

    @staticmethod
    def _monitor(title: str, view: VideoView) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(view)
        return group
