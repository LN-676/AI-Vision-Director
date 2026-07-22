from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class PerformancePanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.metrics = QPlainTextEdit()
        self.metrics.setReadOnly(True)
        QVBoxLayout(self).addWidget(self.metrics)

    def set_snapshot(self, snapshot) -> None:
        average_fps = snapshot.average_fps or 0.0
        stability = snapshot.tracking_stability or 0.0
        latency = snapshot.end_to_end_p95_ms or 0.0
        self.metrics.setPlainText(
            "\n".join(
                (
                    f"Frames: {snapshot.frame_count}",
                    f"FPS: {average_fps:.2f}",
                    f"Tracking stability: {stability:.1%}",
                    f"Dropped frames: {snapshot.total_dropped_frames}",
                    f"P95 latency: {latency:.2f} ms",
                )
            )
        )
