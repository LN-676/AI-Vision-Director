"""Benchmark Center for sequential comparison of up to five models."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Iterable

from PySide6.QtCore import QObject, QPointF, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
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
from autocamtracker.evaluation.auto_benchmark import (
    AutoBenchmarkRequest,
    AutoBenchmarkRunner,
    BenchmarkCancelled,
    BenchmarkModelPair,
    BenchmarkRunControl,
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
    ("Detection proxy", "Detection proxy", 3),
    ("Tracking proxy", "Tracking proxy", 3),
    ("ReID proxy", "ReID proxy", 3),
    ("Feature count", "Feature count", 0),
    ("Rounds", "Rounds", 0),
    ("Scene cuts", "Scene cuts", 0),
    ("Proxy reacquire", "Proxy reacquire rate", 3),
    ("Reacquire ms", "Reacquire time ms", 1),
    ("FPS std", "FPS std", 2),
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
        self.setMinimumHeight(220)

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
    cancelled = Signal()
    failed = Signal(str)
    progressed = Signal(int, int, str)

    def __init__(self, request, runner, control=None) -> None:
        super().__init__()
        self.request = request
        self.runner = runner
        self.control = control

    @Slot()
    def run(self) -> None:
        try:
            kwargs = {
                "progress": (
                    lambda current, total, text: self.progressed.emit(
                        current,
                        total,
                        text,
                    )
                )
            }
            if self.control is not None:
                kwargs["control"] = self.control
            results = self.runner.run(self.request, **kwargs)
            self.completed.emit(results)
        except BenchmarkCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class BenchmarkProgressDialog(QDialog):
    """Small non-modal progress window for a running Quick Auto benchmark."""

    def __init__(
        self,
        control: BenchmarkRunControl,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.control = control
        self._started_at = perf_counter()
        self._paused_at: float | None = None
        self._paused_seconds = 0.0
        self._current = 0
        self._total = 1
        self._finished = False

        self.setWindowTitle("Quick Auto Progress")
        self.setMinimumWidth(500)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)

        layout = QVBoxLayout(self)
        title = QLabel("Quick Auto benchmark")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(title)

        self.task = QLabel("Preparing benchmark…")
        self.task.setWordWrap(True)
        self.task.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.task)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress_percent = QLabel("0%")
        self.progress_percent.setMinimumWidth(44)
        self.progress_percent.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.progress_percent)
        layout.addLayout(progress_row)

        timing = QGridLayout()
        timing.addWidget(QLabel("Elapsed"), 0, 0)
        timing.addWidget(QLabel("Estimated remaining"), 1, 0)
        timing.addWidget(QLabel("Estimated finish"), 2, 0)
        self.elapsed = QLabel("0s")
        self.remaining = QLabel("Calculating…")
        self.finishes_at = QLabel("Calculating…")
        timing.addWidget(self.elapsed, 0, 1)
        timing.addWidget(self.remaining, 1, 1)
        timing.addWidget(self.finishes_at, 2, 1)
        timing.setColumnStretch(1, 1)
        layout.addLayout(timing)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.pause_button = QPushButton("Pause")
        self.stop_button = QPushButton("Stop")
        self.pause_button.clicked.connect(self._toggle_pause)
        self.stop_button.clicked.connect(self._stop)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(1_000)
        self._timer.timeout.connect(self._refresh_timing)
        self._timer.start()

    def update_progress(self, current: int, total: int, text: str) -> None:
        self._current = max(0, int(current))
        self._total = max(1, int(total))
        self.progress.setRange(0, self._total)
        self.progress.setValue(min(self._current, self._total))
        self.progress_percent.setText(
            f"{min(100, round(self._current * 100 / self._total))}%"
        )
        self.task.setText(text)
        self._refresh_timing()

    def finish(self, text: str, *, successful: bool) -> None:
        self._finished = True
        self._timer.stop()
        if successful:
            self._current = self._total
            self.progress.setValue(self.progress.maximum())
            self.progress_percent.setText("100%")
            self.remaining.setText("0s")
            self.finishes_at.setText("Complete")
        else:
            self.remaining.setText("—")
            self.finishes_at.setText("—")
        self.task.setText(text)
        self.pause_button.setEnabled(False)
        self.stop_button.setText("Close")
        self.stop_button.setEnabled(True)
        try:
            self.stop_button.clicked.disconnect(self._stop)
        except (RuntimeError, TypeError):
            pass
        self.stop_button.clicked.connect(self.close)
        self._refresh_timing()

    @Slot()
    def _toggle_pause(self) -> None:
        if self.control.paused:
            self.control.resume()
            if self._paused_at is not None:
                self._paused_seconds += perf_counter() - self._paused_at
                self._paused_at = None
            self.pause_button.setText("Pause")
            self.task.setText(
                self.task.text().removesuffix(" • paused")
            )
        else:
            self.control.pause()
            self._paused_at = perf_counter()
            self.pause_button.setText("Resume")
            self.task.setText(f"{self.task.text()} • paused")
        self._refresh_timing()

    @Slot()
    def _stop(self) -> None:
        self.control.cancel()
        self.task.setText("Stopping Quick Auto safely…")
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)

    @Slot()
    def _refresh_timing(self) -> None:
        elapsed = self._active_elapsed()
        self.elapsed.setText(_format_duration(elapsed))
        if self._finished:
            return
        if self.control.paused:
            self.remaining.setText("Paused")
            self.finishes_at.setText("Paused")
            return
        if self._current <= 0 or elapsed < 1.0:
            self.remaining.setText("Calculating…")
            self.finishes_at.setText("Calculating…")
            return
        rate = self._current / elapsed
        seconds = max(0.0, (self._total - self._current) / rate)
        self.remaining.setText(f"About {_format_duration(seconds)}")
        finish = datetime.now() + timedelta(seconds=seconds)
        self.finishes_at.setText(finish.strftime("%H:%M:%S"))

    def _active_elapsed(self) -> float:
        paused = self._paused_seconds
        if self._paused_at is not None:
            paused += perf_counter() - self._paused_at
        return max(0.0, perf_counter() - self._started_at - paused)


class BenchmarkPanel(QWidget):
    resultsChanged = Signal(object)

    def __init__(self, model_dir: Path, output_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.model_dir = Path(model_dir)
        self.output_dir = Path(output_dir)
        self.results: list[ModelBenchmarkResult] = []
        self._thread: QThread | None = None
        self._worker: _BenchmarkWorker | None = None
        self._run_control: BenchmarkRunControl | None = None
        self._progress_dialog: BenchmarkProgressDialog | None = None
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

        self.setup_grid = QGridLayout()
        self.setup_grid.setHorizontalSpacing(16)
        self.setup_grid.setVerticalSpacing(10)
        self.setup_grid.setColumnStretch(0, 1)
        self.setup_grid.setColumnStretch(1, 1)
        self.video_path = QLineEdit()
        self.latest_recording_button = QPushButton("Latest Recording")
        self.latest_recording_button.clicked.connect(
            self._use_latest_recording
        )
        self.annotation_path = QLineEdit()
        self.annotation_field = self._path_row(
            self.annotation_path,
            self._choose_annotations,
        )
        self.setup_grid.addWidget(
            self._setup_cell(
                "Benchmark video",
                self._video_row(),
            ),
            0,
            0,
        )
        self.setup_grid.addWidget(
            self._setup_cell(
                "Ground truth JSONL (Verified only)",
                self.annotation_field,
            ),
            0,
            1,
        )
        self.dataset_version = QLineEdit("local-golden-v1")
        self.mode = QComboBox()
        self.mode.addItem("Quick Auto — no annotations", "quick_auto")
        self.mode.addItem("Verified Detection/Tracking — JSONL", "verified")
        self.tracker = QComboBox()
        self.tracker.addItem("ByteTrack", "bytetrack")
        self.tracker.addItem("BoT-SORT", "botsort")
        self.tracker.addItem("Deep OC-SORT", "deepocsort")
        self.setup_grid.addWidget(
            self._setup_cell("Benchmark mode", self.mode),
            1,
            0,
        )
        self.setup_grid.addWidget(
            self._setup_cell("Dataset version", self.dataset_version),
            1,
            1,
        )
        layout.addLayout(self.setup_grid)

        run_options = QHBoxLayout()
        self.rounds = QSpinBox()
        self.rounds.setRange(1, 5)
        self.rounds.setValue(3)
        self.feature_limit = QSpinBox()
        self.feature_limit.setRange(1, 500)
        self.feature_limit.setValue(50)
        self.duration_seconds = QSpinBox()
        self.duration_seconds.setRange(0, 86_400)
        self.duration_seconds.setValue(0)
        self.duration_seconds.setSpecialValueText("Full video")
        for label_text, widget in (
            ("Tracker", self.tracker),
            ("Measured rounds", self.rounds),
            ("Feature limit", self.feature_limit),
            ("Duration (seconds)", self.duration_seconds),
        ):
            run_options.addWidget(QLabel(label_text))
            run_options.addWidget(widget)
        layout.addLayout(run_options)

        self.usage_hint = QLabel(
            "Quick Auto needs only a video. It enrolls a frozen feature gallery, "
            "then reports three-round proxy and performance metrics."
        )
        self.usage_hint.setWordWrap(True)
        self.usage_hint.setStyleSheet("color: #687386;")
        layout.addWidget(self.usage_hint)

        self.model_table = QTableWidget(0, 3)
        self.model_table.setMinimumHeight(120)
        self.model_table.setHorizontalHeaderLabels(
            ("Compare", "Detection model", "ReID model")
        )
        self.model_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.model_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.model_table.setMaximumHeight(150)
        self.model_table.itemChanged.connect(self._selection_changed)
        layout.addWidget(
            QLabel(f"Select 1–{MAX_COMPARE_MODELS} Detection × ReID combinations")
        )
        layout.addWidget(self.model_table)

        buttons = QHBoxLayout()
        self.run_button = QPushButton("Run Selected Combinations")
        self.show_progress_button = QPushButton("Show Progress")
        self.show_progress_button.setEnabled(False)
        self.import_button = QPushButton("Import Results…")
        self.export_button = QPushButton("Export Comparison…")
        self.run_button.clicked.connect(self.run_selected)
        self.show_progress_button.clicked.connect(self.show_progress_dialog)
        self.import_button.clicked.connect(self.import_results)
        self.export_button.clicked.connect(self.export_results)
        for button in (
            self.run_button,
            self.show_progress_button,
            self.import_button,
            self.export_button,
        ):
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            buttons.addWidget(button, 1)
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
        self.result_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.result_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.result_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.result_table.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.result_table.setMinimumHeight(100)
        self.result_table.setToolTip(
            "Drag the bottom and right scroll bars to inspect all benchmark metrics."
        )
        self.result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.result_table.currentCellChanged.connect(self._show_shot_details)
        self.shot_table = QTableWidget(0, 8)
        self.shot_table.setMinimumHeight(90)
        self.shot_table.setHorizontalHeaderLabels(
            (
                "Shot",
                "Camera label",
                "Start frame",
                "End frame",
                "Frames",
                "Detection coverage",
                "ReID match coverage",
                "Unique tracks",
            )
        )
        self.shot_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.shot_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.shot_table.itemChanged.connect(self._shot_label_changed)
        result_region = QSplitter(Qt.Orientation.Vertical)
        result_region.addWidget(self.result_table)
        result_region.addWidget(self.shot_table)
        result_region.setSizes([220, 130])
        splitter.addWidget(self.chart)
        splitter.addWidget(result_region)
        splitter.setSizes([330, 350])
        layout.addWidget(splitter, 1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def set_models(
        self,
        detection_paths: Iterable[Path],
        reid_paths: Iterable[Path],
    ) -> None:
        selected = {
            (str(pair.detection_model), str(pair.reid_model))
            for pair in self.selected_model_pairs()
        }
        detectors = list(dict.fromkeys(Path(path) for path in detection_paths))
        reid_models = list(dict.fromkeys(Path(path) for path in reid_paths))
        pairs = [
            BenchmarkModelPair(detector, reid)
            for detector in detectors
            for reid in reid_models
        ]
        self._updating_checks = True
        self.model_table.setRowCount(len(pairs))
        for row, pair in enumerate(pairs):
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check.setCheckState(
                Qt.CheckState.Checked
                if (
                    str(pair.detection_model),
                    str(pair.reid_model),
                )
                in selected
                else Qt.CheckState.Unchecked
            )
            detection = QTableWidgetItem(pair.detection_model.name)
            detection.setData(
                Qt.ItemDataRole.UserRole,
                str(pair.detection_model),
            )
            detection.setToolTip(str(pair.detection_model))
            detection.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            reid = QTableWidgetItem(pair.reid_model.name)
            reid.setData(Qt.ItemDataRole.UserRole, str(pair.reid_model))
            reid.setToolTip(str(pair.reid_model))
            reid.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            self.model_table.setItem(row, 0, check)
            self.model_table.setItem(row, 1, detection)
            self.model_table.setItem(row, 2, reid)
        self._updating_checks = False

    def selected_model_pairs(self) -> list[BenchmarkModelPair]:
        pairs = []
        for row in range(self.model_table.rowCount()):
            check = self.model_table.item(row, 0)
            detection = self.model_table.item(row, 1)
            reid = self.model_table.item(row, 2)
            if (
                check
                and detection
                and reid
                and check.checkState() == Qt.CheckState.Checked
            ):
                pairs.append(
                    BenchmarkModelPair(
                        Path(
                            str(
                                detection.data(Qt.ItemDataRole.UserRole)
                            )
                        ),
                        Path(str(reid.data(Qt.ItemDataRole.UserRole))),
                    )
                )
        return pairs

    def selected_model_paths(self) -> list[Path]:
        return [pair.detection_model for pair in self.selected_model_pairs()]

    @Slot()
    def run_selected(self) -> None:
        pairs = self.selected_model_pairs()
        try:
            if self.mode.currentData() == "quick_auto":
                request = AutoBenchmarkRequest(
                    video_path=Path(self.video_path.text().strip()),
                    model_pairs=tuple(pairs),
                    tracker=str(self.tracker.currentData()),
                    dataset_version=(
                        self.dataset_version.text().strip() or "quick-auto-v1"
                    ),
                    rounds=self.rounds.value(),
                    feature_limit=self.feature_limit.value(),
                    duration_seconds=float(self.duration_seconds.value()),
                )
                runner = AutoBenchmarkRunner()
            else:
                request = VisionBenchmarkRequest(
                    video_path=Path(self.video_path.text().strip()),
                    annotation_path=Path(
                        self.annotation_path.text().strip()
                    ),
                    model_paths=tuple(
                        dict.fromkeys(
                            pair.detection_model for pair in pairs
                        )
                    ),
                    tracker=str(self.tracker.currentData()),
                    dataset_version=(
                        self.dataset_version.text().strip()
                        or "local-golden-v1"
                    ),
                )
                runner = VisionBenchmarkRunner()
            request.validate()
        except Exception as exc:
            QMessageBox.warning(self, "Benchmark setup", str(exc))
            return
        self.run_button.setEnabled(False)
        self.status.setText("Starting benchmark…")
        quick_auto = self.mode.currentData() == "quick_auto"
        self._run_control = BenchmarkRunControl() if quick_auto else None
        if self._progress_dialog is not None:
            self._progress_dialog.close()
        self._progress_dialog = (
            BenchmarkProgressDialog(self._run_control, self)
            if self._run_control is not None
            else None
        )
        if self._progress_dialog is not None:
            self._progress_dialog.show()
            self._progress_dialog.raise_()
            self.show_progress_button.setEnabled(True)
        self._thread = QThread(self)
        self._worker = _BenchmarkWorker(
            request,
            runner,
            control=self._run_control,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progressed.connect(self._show_progress)
        self._worker.completed.connect(self._benchmark_complete)
        self._worker.cancelled.connect(self._benchmark_cancelled)
        self._worker.failed.connect(self._benchmark_failed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.cancelled.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    @Slot()
    def show_progress_dialog(self) -> None:
        if self._progress_dialog is None:
            return
        self._progress_dialog.show()
        self._progress_dialog.raise_()
        self._progress_dialog.activateWindow()

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
        if self.results:
            self.result_table.selectRow(0)
            self._show_shot_details(0, 0, -1, -1)
        else:
            self.shot_table.setRowCount(0)

    def _path_row(self, field: QLineEdit, callback) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Browse…")
        button.clicked.connect(callback)
        row.addWidget(field, 1)
        row.addWidget(button)
        return widget

    def _video_row(self) -> QWidget:
        widget = self._path_row(self.video_path, self._choose_video)
        widget.layout().addWidget(self.latest_recording_button)
        return widget

    @staticmethod
    def _setup_cell(label_text: str, field: QWidget) -> QWidget:
        widget = QWidget()
        column = QVBoxLayout(widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(QLabel(label_text))
        column.addWidget(field)
        return widget

    def _choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Benchmark video",
            str(self.output_dir),
            "Video files (*.mp4 *.mov *.mkv *.avi)",
        )
        if path:
            self.video_path.setText(path)

    def _use_latest_recording(self) -> None:
        recordings = sorted(
            self.output_dir.glob("live-*/source.mp4"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if recordings:
            self.video_path.setText(str(recordings[0]))
            self.status.setText(f"Using recorded stream: {recordings[0]}")
            return
        QMessageBox.information(
            self,
            "Latest recording",
            "No recorded stream was found. Record one from Track Page first.",
        )

    def _choose_annotations(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Ground-truth annotations", "", "JSONL files (*.jsonl)"
        )
        if path:
            self.annotation_path.setText(path)

    def _selection_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_checks or item.column() != 0:
            return
        selected = self.selected_model_pairs()
        if len(selected) <= MAX_COMPARE_MODELS:
            return
        self._updating_checks = True
        item.setCheckState(Qt.CheckState.Unchecked)
        self._updating_checks = False
        self.status.setText(
            f"You can compare at most {MAX_COMPARE_MODELS} combinations."
        )

    @Slot()
    def _mode_changed(self, _index: int | None = None) -> None:
        quick = self.mode.currentData() == "quick_auto"
        self.annotation_field.setEnabled(not quick)
        self.rounds.setEnabled(quick)
        self.feature_limit.setEnabled(quick)
        self.duration_seconds.setEnabled(quick)
        self.usage_hint.setText(
            (
                "Quick Auto needs only a video. Each pair enrolls a frozen "
                "gallery first, then reports multi-round proxy metrics by shot."
            )
            if quick
            else (
                "Verified mode requires matching JSONL ground truth and reports "
                "standard Detection/Tracking accuracy. ReID identity verification "
                "needs confirmed identity events."
            )
        )
        if self._thread is None:
            self.status.setText(
                (
                    "Quick Auto: proxy metrics only; no ground-truth accuracy "
                    "claims."
                )
                if quick
                else (
                    "Verified mode: annotations are required for standard "
                    "Detection/Tracking metrics."
                )
            )

    @Slot(int, int, int, int)
    def _show_shot_details(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        if not 0 <= current_row < len(self.results):
            self.shot_table.setRowCount(0)
            return
        shots = list(self.results[current_row].metadata.get("shots", []))
        self.shot_table.blockSignals(True)
        self.shot_table.setRowCount(len(shots))
        for row, shot in enumerate(shots):
            values = (
                shot.get("shot_id"),
                shot.get(
                    "camera_label",
                    f"Shot {shot.get('shot_id', row)}",
                ),
                shot.get("start_frame"),
                shot.get("end_frame"),
                shot.get("frames"),
                _format_ratio(shot.get("detection_coverage")),
                _format_ratio(shot.get("reid_match_coverage")),
                shot.get("unique_tracks"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column != 1:
                    item.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                    )
                self.shot_table.setItem(row, column, item)
        self.shot_table.blockSignals(False)

    @Slot(QTableWidgetItem)
    def _shot_label_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 1:
            return
        result_row = self.result_table.currentRow()
        if not 0 <= result_row < len(self.results):
            return
        shots = self.results[result_row].metadata.get("shots", [])
        if 0 <= item.row() < len(shots):
            shots[item.row()]["camera_label"] = (
                item.text().strip()
                or f"Shot {shots[item.row()].get('shot_id', item.row())}"
            )

    @Slot(int, int, str)
    def _show_progress(self, current: int, total: int, text: str) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(min(current, max(1, total)))
        self.status.setText(text)
        if self._progress_dialog is not None:
            self._progress_dialog.update_progress(current, total, text)

    @Slot(object)
    def _benchmark_complete(self, results) -> None:
        self.set_results(results)
        self.run_button.setEnabled(True)
        self.progress.setValue(self.progress.maximum())
        quick = bool(
            self.results
            and self.results[0].metadata.get("mode") == "quick_auto"
        )
        self.status.setText(
            (
                "Quick Auto complete. Proxy scores compare consistency and "
                "performance, not ground-truth identity accuracy."
            )
            if quick
            else (
                "Verified benchmark complete. Scores are comparable within "
                "this dataset version."
            )
        )
        if self._progress_dialog is not None:
            self._progress_dialog.finish(
                "Quick Auto complete. Results are ready.",
                successful=True,
            )

    @Slot(str)
    def _benchmark_failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.status.setText(f"Benchmark failed: {message}")
        if self._progress_dialog is not None:
            self._progress_dialog.finish(
                f"Quick Auto failed: {message}",
                successful=False,
            )
        QMessageBox.warning(self, "Benchmark failed", message)

    @Slot()
    def _benchmark_cancelled(self) -> None:
        self.run_button.setEnabled(True)
        self.status.setText("Quick Auto stopped.")
        if self._progress_dialog is not None:
            self._progress_dialog.finish(
                "Quick Auto stopped.",
                successful=False,
            )

    @Slot()
    def _thread_finished(self) -> None:
        self._worker = None
        self._thread = None
        self._run_control = None


def _format_metric(value, *, decimals: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{decimals}f}"


def _format_ratio(value) -> str:
    return "—" if value is None else f"{float(value):.1%}"


def _format_duration(seconds: float) -> str:
    total = max(0, round(float(seconds)))
    hours, remainder = divmod(total, 3_600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
