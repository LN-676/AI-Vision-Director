"""Benchmark Center for sequential comparison of up to five models."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QObject, QPointF, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autocamtracker.evaluation.benchmark import (
    MAX_COMPARE_MODELS,
    ModelBenchmarkResult,
    load_results,
    save_results,
)
from autocamtracker.evaluation.vision_benchmark import (
    VisionBenchmarkRequest,
    VisionBenchmarkRunner,
)


CHART_COLORS = (
    QColor("#00c2ff"),
    QColor("#ff5c8a"),
    QColor("#7ed957"),
    QColor("#ffb000"),
    QColor("#a78bfa"),
)

RESULT_COLUMNS = (
    ("Model", None, None),
    ("Score", None, None),
    ("Coverage", None, None),
    ("Detection ratio", None, None),
    ("Tracking ratio", None, None),
    ("Identity ratio", None, None),
    ("Framing ratio", None, None),
    ("Control ratio", None, None),
    ("Realtime ratio", None, None),
    ("mAP50", "mAP50", 3),
    ("mAP50-95", "mAP50-95", 3),
    ("Precision", "Precision", 3),
    ("Recall", "Recall", 3),
    ("HOTA", "HOTA", 3),
    ("IDF1", "IDF1", 3),
    ("MOTA", "MOTA", 3),
    ("ID switches", "ID switches", 0),
    ("Fragmentation", "Fragmentation", 0),
    ("Rank-1", "Rank-1", 3),
    ("Rank-5", "Rank-5", 3),
    ("MRR", "MRR", 3),
    ("False reacquire", "False reacquire rate", 3),
    ("Reacquire success", "Reacquire success rate", 3),
    ("FPS", "FPS", 1),
    ("P50 ms", "Latency p50 ms", 1),
    ("P95 ms", "Latency p95 ms", 1),
    ("P99 ms", "Latency p99 ms", 1),
    ("Dropped", "Dropped frame rate", 3),
    ("Overshoot", "Overshoot", 3),
    ("Settling ms", "Settling time ms", 1),
    ("Jitter", "Jitter", 3),
    ("Out of frame", "Target out-of-frame ratio", 3),
)


class BenchmarkRadarChart(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.results: list[ModelBenchmarkResult] = []
        self.setMinimumHeight(300)

    def set_results(self, results: Iterable[ModelBenchmarkResult]) -> None:
        self.results = list(results)[:MAX_COMPARE_MODELS]
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#121722"))
        if not self.results:
            painter.setPen(QColor("#aab4c3"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Run or import a benchmark to compare models")
            return
        axis_names = ("Detection", "Tracking", "Identity", "Framing", "Control", "Realtime")
        center = QPointF(self.width() * 0.43, self.height() * 0.52)
        radius = min(self.width() * 0.30, self.height() * 0.36)
        points_by_level: list[QPolygonF] = []
        import math

        for level in range(1, 6):
            points_by_level.append(
                QPolygonF(
                    [
                        QPointF(
                            center.x() + radius * level / 5 * math.cos(-math.pi / 2 + index * 2 * math.pi / 6),
                            center.y() + radius * level / 5 * math.sin(-math.pi / 2 + index * 2 * math.pi / 6),
                        )
                        for index in range(6)
                    ]
                )
            )
        painter.setPen(QPen(QColor("#344055"), 1))
        for polygon in points_by_level:
            painter.drawPolygon(polygon)
        outer = points_by_level[-1]
        for point in outer:
            painter.drawLine(center, point)
        painter.setFont(QFont(painter.font().family(), 9))
        painter.setPen(QColor("#dce4ef"))
        for name, point in zip(axis_names, outer):
            offset_x = -35 if point.x() < center.x() else -5
            offset_y = -8 if point.y() < center.y() else 18
            painter.drawText(QPointF(point.x() + offset_x, point.y() + offset_y), name)

        for result_index, result in enumerate(self.results):
            values = (
                result.score.axes.detection,
                result.score.axes.tracking,
                result.score.axes.identity,
                result.score.axes.framing,
                result.score.axes.control,
                result.score.axes.realtime,
            )
            polygon = QPolygonF()
            for index, value in enumerate(values):
                ratio = float(value or 0.0)
                polygon.append(
                    QPointF(
                        center.x() + radius * ratio * math.cos(-math.pi / 2 + index * 2 * math.pi / 6),
                        center.y() + radius * ratio * math.sin(-math.pi / 2 + index * 2 * math.pi / 6),
                    )
                )
            color = CHART_COLORS[result_index]
            fill = QColor(color)
            fill.setAlpha(45)
            painter.setBrush(fill)
            painter.setPen(QPen(color, 2))
            painter.drawPolygon(polygon)

        legend_x = self.width() * 0.73
        legend_y = 45
        for index, result in enumerate(self.results):
            color = CHART_COLORS[index]
            painter.fillRect(int(legend_x), int(legend_y + index * 45), 12, 12, color)
            painter.setPen(QColor("#f5f7fa"))
            painter.setFont(QFont(painter.font().family(), 10, QFont.Weight.DemiBold))
            painter.drawText(
                QPointF(legend_x + 20, legend_y + 11 + index * 45),
                f"{result.model_name}: {result.score.total:,}",
            )
            painter.setPen(QColor("#9eabbc"))
            painter.setFont(QFont(painter.font().family(), 8))
            painter.drawText(
                QPointF(legend_x + 20, legend_y + 27 + index * 45),
                f"{result.score.profile} · coverage {result.score.coverage:.0%}",
            )


class _BenchmarkWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    progressed = Signal(int, int, str)

    def __init__(self, request: VisionBenchmarkRequest) -> None:
        super().__init__()
        self.request = request

    @Slot()
    def run(self) -> None:
        try:
            results = VisionBenchmarkRunner().run(
                self.request,
                progress=lambda current, total, text: self.progressed.emit(
                    current, total, text
                ),
            )
            self.completed.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class BenchmarkPanel(QWidget):
    resultsChanged = Signal(object)

    def __init__(self, model_dir: Path, output_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.model_dir = Path(model_dir)
        self.output_dir = Path(output_dir)
        self.results: list[ModelBenchmarkResult] = []
        self._thread: QThread | None = None
        self._worker: _BenchmarkWorker | None = None
        self._updating_checks = False

        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("Benchmark Center")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.score_summary = QLabel("No score")
        self.score_summary.setStyleSheet("font-size: 18px; color: #00c2ff;")
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(self.score_summary)
        layout.addLayout(heading)

        setup = QFormLayout()
        self.video_path = QLineEdit()
        self.annotation_path = QLineEdit()
        setup.addRow("Golden video", self._path_row(self.video_path, self._choose_video))
        setup.addRow(
            "Ground truth JSONL",
            self._path_row(self.annotation_path, self._choose_annotations),
        )
        self.dataset_version = QLineEdit("local-golden-v1")
        self.tracker = QComboBox()
        self.tracker.addItem("ByteTrack", "bytetrack")
        self.tracker.addItem("BoT-SORT", "botsort")
        self.tracker.addItem("Deep OC-SORT", "deepocsort")
        setup.addRow("Dataset version", self.dataset_version)
        setup.addRow("Tracker", self.tracker)
        layout.addLayout(setup)

        self.model_table = QTableWidget(0, 2)
        self.model_table.setHorizontalHeaderLabels(("Compare", "Detection model"))
        self.model_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.model_table.setMaximumHeight(180)
        self.model_table.itemChanged.connect(self._selection_changed)
        layout.addWidget(QLabel(f"Select 1–{MAX_COMPARE_MODELS} models"))
        layout.addWidget(self.model_table)

        buttons = QHBoxLayout()
        self.run_button = QPushButton("Run Selected Models")
        import_button = QPushButton("Import Results…")
        export_button = QPushButton("Export Comparison…")
        self.run_button.clicked.connect(self.run_selected)
        import_button.clicked.connect(self.import_results)
        export_button.clicked.connect(self.export_results)
        buttons.addWidget(self.run_button)
        buttons.addWidget(import_button)
        buttons.addWidget(export_button)
        layout.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.status = QLabel(
            "Models run sequentially. Accuracy scoring requires ground-truth annotations."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.chart = BenchmarkRadarChart()
        self.result_table = QTableWidget(0, len(RESULT_COLUMNS))
        self.result_table.setHorizontalHeaderLabels(
            tuple(column[0] for column in RESULT_COLUMNS)
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        splitter.addWidget(self.chart)
        splitter.addWidget(self.result_table)
        splitter.setSizes([360, 220])
        layout.addWidget(splitter, 1)

    def set_models(self, paths: Iterable[Path]) -> None:
        selected = set(self.selected_model_paths())
        unique_paths = list(dict.fromkeys(Path(path) for path in paths))
        self._updating_checks = True
        self.model_table.setRowCount(len(unique_paths))
        for row, path in enumerate(unique_paths):
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check.setCheckState(
                Qt.CheckState.Checked if path in selected else Qt.CheckState.Unchecked
            )
            name = QTableWidgetItem(path.name)
            name.setData(Qt.ItemDataRole.UserRole, str(path))
            name.setToolTip(str(path))
            name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.model_table.setItem(row, 0, check)
            self.model_table.setItem(row, 1, name)
        self._updating_checks = False

    def selected_model_paths(self) -> list[Path]:
        paths = []
        for row in range(self.model_table.rowCount()):
            check = self.model_table.item(row, 0)
            name = self.model_table.item(row, 1)
            if check and name and check.checkState() == Qt.CheckState.Checked:
                paths.append(Path(str(name.data(Qt.ItemDataRole.UserRole))))
        return paths

    @Slot()
    def run_selected(self) -> None:
        models = self.selected_model_paths()
        try:
            request = VisionBenchmarkRequest(
                video_path=Path(self.video_path.text().strip()),
                annotation_path=Path(self.annotation_path.text().strip()),
                model_paths=tuple(models),
                tracker=str(self.tracker.currentData()),
                dataset_version=self.dataset_version.text().strip() or "local-golden-v1",
            )
            request.validate()
        except Exception as exc:
            QMessageBox.warning(self, "Benchmark setup", str(exc))
            return
        self.run_button.setEnabled(False)
        self.status.setText("Starting benchmark…")
        self._thread = QThread(self)
        self._worker = _BenchmarkWorker(request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progressed.connect(self._show_progress)
        self._worker.completed.connect(self._benchmark_complete)
        self._worker.failed.connect(self._benchmark_failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    def import_results(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Benchmark Results", str(self.output_dir), "JSON files (*.json)"
        )
        if not path:
            return
        try:
            self.set_results(load_results(path))
            self.status.setText(f"Imported {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))

    def export_results(self) -> None:
        if not self.results:
            QMessageBox.information(self, "Benchmark", "There are no results to export.")
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Benchmark Comparison",
            str(self.output_dir / "model-comparison.json"),
            "JSON files (*.json)",
        )
        if path:
            save_results(path, self.results)
            self.status.setText(f"Exported {path}")

    def set_results(self, results: Iterable[ModelBenchmarkResult]) -> None:
        self.results = list(results)[:MAX_COMPARE_MODELS]
        self.chart.set_results(self.results)
        self.result_table.setRowCount(len(self.results))
        for row, result in enumerate(self.results):
            values = [
                result.model_name,
                f"{result.score.total:,}",
                f"{result.score.coverage:.0%}",
                _format_ratio(result.score.axes.detection),
                _format_ratio(result.score.axes.tracking),
                _format_ratio(result.score.axes.identity),
                _format_ratio(result.score.axes.framing),
                _format_ratio(result.score.axes.control),
                _format_ratio(result.score.axes.realtime),
            ]
            values.extend(
                _format_metric(
                    result.metrics.get(metric_name),
                    decimals=int(decimals or 0),
                )
                for _, metric_name, decimals in RESULT_COLUMNS[9:]
            )
            for column, value in enumerate(values):
                self.result_table.setItem(row, column, QTableWidgetItem(value))
        if self.results:
            leader = max(self.results, key=lambda item: item.score.total)
            self.score_summary.setText(f"Top score {leader.score.total:,}")
        else:
            self.score_summary.setText("No score")
        self.resultsChanged.emit(self.results)

    def _path_row(self, field: QLineEdit, callback) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse…")
        button.clicked.connect(callback)
        row.addWidget(field, 1)
        row.addWidget(button)
        return widget

    def _choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Golden benchmark video", "", "Video files (*.mp4 *.mov *.mkv *.avi)"
        )
        if path:
            self.video_path.setText(path)

    def _choose_annotations(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Ground-truth annotations", "", "JSONL files (*.jsonl)"
        )
        if path:
            self.annotation_path.setText(path)

    def _selection_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_checks or item.column() != 0:
            return
        selected = self.selected_model_paths()
        if len(selected) <= MAX_COMPARE_MODELS:
            return
        self._updating_checks = True
        item.setCheckState(Qt.CheckState.Unchecked)
        self._updating_checks = False
        self.status.setText(f"You can compare at most {MAX_COMPARE_MODELS} models.")

    @Slot(int, int, str)
    def _show_progress(self, current: int, total: int, text: str) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(current, max(1, total)))
        self.status.setText(text)

    @Slot(object)
    def _benchmark_complete(self, results) -> None:
        self.set_results(results)
        self.run_button.setEnabled(True)
        self.progress.setValue(self.progress.maximum())
        self.status.setText("Benchmark complete. Scores are comparable within this dataset version.")

    @Slot(str)
    def _benchmark_failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.status.setText(f"Benchmark failed: {message}")
        QMessageBox.warning(self, "Benchmark failed", message)

    @Slot()
    def _thread_finished(self) -> None:
        self._worker = None
        self._thread = None


def _format_metric(value, *, decimals: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{decimals}f}"


def _format_ratio(value) -> str:
    return "—" if value is None else f"{float(value):.1%}"
