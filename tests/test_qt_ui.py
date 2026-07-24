from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import numpy as np
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtWidgets import QApplication

from autocamtracker.bootstrap import build_dependencies
from autocamtracker.product import DISPLAY_NAME, VERSION
from autocamtracker.ui.app import (
    AIVisionDirectorApp,
    AIVisonDirectorApp,
    AppConfig,
    AutoCamTrackerApp,
)
from autocamtracker.ui_qt.controller import overlay_identity_label, video_sync_plan
from autocamtracker.ui_qt.bootstrap import BootstrappedQtDesktop
from autocamtracker.ui_qt.main_window import AIVisionDirectorMainWindow
from autocamtracker.ui_qt.panels.feature_manager_dialog import FeatureManagerDialog
from autocamtracker.ui_qt.panels.benchmark_panel import (
    BenchmarkPanel,
    BenchmarkProgressDialog,
    _format_duration,
)
from autocamtracker.ui_qt.panels.playback_panel import format_timecode
from autocamtracker.ui_qt.panels.source_panel import SourcePanel
from autocamtracker.ui_qt.panels.vehicle_database_panel import VehicleDatabasePanel
from autocamtracker.ui_qt.state import LAYOUT_VERSION, VERSION_KEY, Workspace
from autocamtracker.ui_qt.widgets.video_view import VideoView, qimage_from_bgr
from autocamtracker.evaluation.auto_benchmark import BenchmarkRunControl


class QtUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.qt_app.processEvents()
        self.temp_dir.cleanup()

    def _window(self, settings_path: Path | None = None):
        config = AppConfig(
            telemetry_dir=self.root / "telemetry",
            identity_db_path=self.root / "identity.sqlite3",
            camera_calibration_path=self.root / "calibration.json",
        )
        dependencies = build_dependencies(config)
        settings = QSettings(
            str(settings_path or self.root / "settings.ini"),
            QSettings.Format.IniFormat,
        )
        return AIVisionDirectorMainWindow(
            config, dependencies, settings=settings
        )

    def test_display_label_and_tk_class_aliases_preserve_protocol_version(self) -> None:
        self.assertEqual(DISPLAY_NAME, "AI Vision Director V2.3")
        self.assertEqual(VERSION, "1.0")
        self.assertIs(AIVisonDirectorApp, AIVisionDirectorApp)
        self.assertIs(AutoCamTrackerApp, AIVisionDirectorApp)

    def test_quick_auto_progress_dialog_shows_task_eta_and_controls(self) -> None:
        control = BenchmarkRunControl()
        dialog = BenchmarkProgressDialog(control)
        try:
            dialog.update_progress(
                500,
                4_000,
                "detector + reid: enrolling feature gallery • 25/50 features",
            )
            self.assertEqual(dialog.progress.value(), 500)
            self.assertEqual(dialog.progress_percent.text(), "12%")
            self.assertIn("25/50 features", dialog.task.text())
            self.assertEqual(dialog.pause_button.text(), "Pause")

            dialog.pause_button.click()
            self.assertTrue(control.paused)
            self.assertEqual(dialog.pause_button.text(), "Resume")

            dialog.pause_button.click()
            self.assertFalse(control.paused)
            dialog.stop_button.click()
            self.assertTrue(control.cancelled)
            self.assertFalse(dialog.stop_button.isEnabled())
            self.assertEqual(_format_duration(3_661), "1h 1m")
        finally:
            dialog.close()

    def test_benchmark_action_row_is_equal_and_reopens_progress(self) -> None:
        panel = BenchmarkPanel(self.root / "models", self.root / "output")
        dialog = BenchmarkProgressDialog(BenchmarkRunControl(), panel)
        try:
            panel.resize(1_200, 800)
            panel.show()
            self.qt_app.processEvents()
            buttons = (
                panel.run_button,
                panel.show_progress_button,
                panel.import_button,
                panel.export_button,
            )
            self.assertFalse(panel.show_progress_button.isEnabled())
            self.assertLessEqual(
                max(button.width() for button in buttons)
                - min(button.width() for button in buttons),
                1,
            )

            panel._progress_dialog = dialog
            panel.show_progress_button.setEnabled(True)
            dialog.hide()
            panel.show_progress_button.click()
            self.qt_app.processEvents()
            self.assertTrue(dialog.isVisible())
        finally:
            dialog.close()
            panel.close()

    def test_main_window_smoke_and_unique_docks(self) -> None:
        window = self._window()
        try:
            window.show()
            self.qt_app.processEvents()
            names = [dock.objectName() for dock in window.docks.values()]
            self.assertEqual(window.windowTitle(), DISPLAY_NAME)
            self.assertEqual(len(names), 8)
            self.assertEqual(len(names), len(set(names)))
            self.assertNotIn("playback", window.docks)
            self.assertNotIn("reid", window.docks)
            self.assertEqual(window.monitors.before_view.minimumWidth(), 320)
            self.assertGreaterEqual(window.monitors.after_view.minimumHeight(), 232)
            self.assertTrue(
                window.panels["source"].websocket_url.text().startswith("ws://")
            )
        finally:
            window.close()

    def test_window_toggle_action_hides_and_reopens_panel(self) -> None:
        window = self._window()
        try:
            window.show()
            self.qt_app.processEvents()
            dock = window.docks["source"]
            action = dock.toggleViewAction()
            action.trigger()
            self.qt_app.processEvents()
            self.assertFalse(dock.isVisible())
            action.trigger()
            self.qt_app.processEvents()
            self.assertTrue(dock.isVisible())
        finally:
            window.close()

    def test_page_toolbar_lists_every_page_and_switches_workspace(self) -> None:
        window = self._window()
        try:
            window.show()
            self.qt_app.processEvents()
            self.assertEqual(
                [action.text() for action in window.navigation_actions.values()],
                [
                    "Track Page",
                    "Benchmark",
                ],
            )

            window.navigation_actions["benchmark"].trigger()
            self.qt_app.processEvents()
            self.assertFalse(window.monitors.isVisible())
            self.assertTrue(window.docks["benchmark"].isVisible())
            self.assertTrue(window.docks["models"].isVisible())

            window.navigation_actions["source"].trigger()
            self.qt_app.processEvents()
            self.assertTrue(window.monitors.isVisible())
            self.assertTrue(window.docks["source"].isVisible())
            self.assertFalse(window.docks["benchmark"].isVisible())
        finally:
            window.close()

    def test_source_content_can_shrink_without_forcing_dock_width(self) -> None:
        window = self._window()
        try:
            window.show()
            self.qt_app.processEvents()
            source = window.panels["source"]
            source.set_connection(
                "iPhone server failed: " + "a very long connection error " * 30
            )
            self.qt_app.processEvents()

            self.assertTrue(source.connection.wordWrap())
            self.assertEqual(
                source.connection.sizePolicy().horizontalPolicy(),
                source.connection.sizePolicy().Policy.Ignored,
            )
            self.assertEqual(source.pages.minimumWidth(), 0)
            self.assertLess(window.docks["source"].width(), window.width() * 0.6)
            window.resizeDocks(
                [window.docks["source"]],
                [500],
                Qt.Orientation.Horizontal,
            )
            self.qt_app.processEvents()
            expanded_width = window.docks["source"].width()
            window.resizeDocks(
                [window.docks["source"]],
                [280],
                Qt.Orientation.Horizontal,
            )
            self.qt_app.processEvents()
            self.assertGreater(expanded_width, window.docks["source"].width())
        finally:
            window.close()

    def test_workspace_state_restores_and_reset_returns_to_tracking(self) -> None:
        settings_path = self.root / "workspace.ini"
        first = self._window(settings_path)
        first.show()
        self.qt_app.processEvents()
        first.apply_workspace(Workspace.IDENTITY)
        first.save_workspace()
        self.assertFalse(first.docks["source"].isVisible())
        first.close()
        self.qt_app.processEvents()

        second = self._window(settings_path)
        try:
            second.show()
            self.qt_app.processEvents()
            self.assertEqual(
                int(second.settings.value(VERSION_KEY)), LAYOUT_VERSION
            )
            self.assertFalse(second.docks["source"].isVisible())
            second.reset_workspace()
            self.qt_app.processEvents()
            self.assertTrue(second.docks["source"].isVisible())
            self.assertTrue(
                second.workspace_actions[Workspace.TRACKING].isChecked()
            )
        finally:
            second.close()

    def test_workspace_restores_monitor_splitter_and_custom_layout(self) -> None:
        settings_path = self.root / "custom-workspace.ini"
        first = self._window(settings_path)
        first.show()
        self.qt_app.processEvents()
        first.docks["source"].hide()
        first.monitors.splitter.setSizes([440, 320])
        self.qt_app.processEvents()
        first.save_custom_workspace()
        saved_sizes = first.monitors.splitter.sizes()
        saved_ratio = saved_sizes[0] / sum(saved_sizes)
        first.docks["source"].show()
        first.monitors.splitter.setSizes([320, 440])
        self.qt_app.processEvents()

        self.assertTrue(first.restore_custom_workspace())
        self.qt_app.processEvents()
        self.assertFalse(first.docks["source"].isVisible())
        restored_sizes = first.monitors.splitter.sizes()
        self.assertAlmostEqual(restored_sizes[0] / sum(restored_sizes), saved_ratio, places=2)
        first.close()
        self.qt_app.processEvents()

        second = self._window(settings_path)
        try:
            second.show()
            self.qt_app.processEvents()
            reopened_sizes = second.monitors.splitter.sizes()
            self.assertAlmostEqual(
                reopened_sizes[0] / sum(reopened_sizes), saved_ratio, places=2
            )
            self.assertEqual(second.monitors.splitter.handleWidth(), 12)
            self.assertIn("width: 12px", second.styleSheet())
        finally:
            second.close()

    def test_monitor_maximize_hides_and_restores_docks(self) -> None:
        window = self._window()
        try:
            window.show()
            self.qt_app.processEvents()
            visible_before = {
                key: dock.isVisible() for key, dock in window.docks.items()
            }

            window.toggle_monitor_maximize(True)
            self.qt_app.processEvents()

            self.assertTrue(window.maximize_monitors_action.isChecked())
            self.assertTrue(all(not dock.isVisible() for dock in window.docks.values()))

            window.toggle_monitor_maximize(False)
            self.qt_app.processEvents()

            self.assertEqual(
                {key: dock.isVisible() for key, dock in window.docks.items()},
                visible_before,
            )
        finally:
            window.close()

    def test_qimage_conversion_owns_non_contiguous_bgr_data(self) -> None:
        backing = np.zeros((2, 6, 3), dtype=np.uint8)
        backing[:, ::2] = (10, 20, 30)
        frame = backing[:, ::2]
        self.assertFalse(frame.flags.c_contiguous)

        image = qimage_from_bgr(frame)
        backing.fill(0)
        color = image.pixelColor(0, 0)

        self.assertEqual((image.width(), image.height()), (3, 2))
        self.assertEqual((color.red(), color.green(), color.blue()), (30, 20, 10))

    def test_video_view_letterbox_click_mapping(self) -> None:
        view = VideoView()
        view.resize(640, 480)
        view.set_frame(np.zeros((180, 320, 3), dtype=np.uint8))

        mapped = view.map_to_frame(QPointF(320, 180))

        self.assertIsNotNone(mapped)
        self.assertAlmostEqual(mapped[0], 160.0)
        self.assertAlmostEqual(mapped[1], 90.0)
        self.assertIsNone(view.map_to_frame(QPointF(320, 400)))

    def test_video_sync_plan_skips_late_frames_instead_of_slow_motion(self) -> None:
        late = video_sync_plan(
            start_frame=0,
            current_frame=5,
            source_fps=30.0,
            playback_speed=1.0,
            elapsed_seconds=0.5,
        )
        early = video_sync_plan(
            start_frame=0,
            current_frame=16,
            source_fps=30.0,
            playback_speed=1.0,
            elapsed_seconds=0.5,
        )

        self.assertEqual(late.frames_to_skip, 10)
        self.assertAlmostEqual(late.lag_ms, 1000.0 / 3.0)
        self.assertEqual(late.wait_seconds, 0.0)
        self.assertEqual(early.frames_to_skip, 0)
        self.assertAlmostEqual(early.wait_seconds, 1.0 / 30.0)

    def test_timeline_uses_frame_accurate_timecode(self) -> None:
        self.assertEqual(format_timecode(300, 30.0), "00:00:10:00")
        self.assertEqual(format_timecode(45, 30.0), "00:00:01:15")

    def test_detection_overlay_uses_requested_80_pixel_font_height(self) -> None:
        from autocamtracker.ui_qt.controller import QtRuntimeController

        self.assertEqual(QtRuntimeController.OVERLAY_FONT_HEIGHT, 80)
        self.assertEqual(
            overlay_identity_label(selected=True, track_id=59, global_id=2),
            "GID 2",
        )
        self.assertEqual(
            overlay_identity_label(selected=False, track_id=59, global_id=2),
            "LID 59  GID 2",
        )

    def test_vehicle_database_is_read_only_and_double_click_opens_features(self) -> None:
        panel = VehicleDatabasePanel()
        panel.set_vehicles(
            [
                SimpleNamespace(
                    vehicle_id=2,
                    display_name="2",
                    class_name="car",
                    last_track_id=59,
                    master_feature_count=31,
                )
            ]
        )
        opened: list[int] = []
        panel.manageFeaturesRequested.connect(opened.append)

        panel._open_feature_manager(0, 2)

        self.assertEqual(opened, [2])
        self.assertEqual(
            panel.hint.text(),
            "Double-click a vehicle to open its photo gallery.",
        )
        for column in range(panel.table.columnCount()):
            self.assertFalse(
                bool(
                    panel.table.item(0, column).flags()
                    & Qt.ItemFlag.ItemIsEditable
                )
            )
        self.assertEqual(panel.manual_feature_button.text(), "Add Manual Feature")
        self.assertEqual(
            panel.auto_feature_button.text(), "Start / Stop Auto Feature"
        )
        changed: list[float] = []
        panel.findThresholdChanged.connect(changed.append)
        panel.find_threshold.setValue(0.8)
        self.assertEqual(changed, [0.8])

    def test_source_panel_switches_to_only_the_selected_source_page(self) -> None:
        panel = SourcePanel()
        panel.set_iphone_url("ws://mac.local:8765/ws/tracking")
        panel.source.setCurrentIndex(panel.source.findData("video_url"))

        self.assertEqual(panel.pages.currentIndex(), panel.source.currentIndex())
        self.assertIs(panel.pages.currentWidget(), panel.video_url.parentWidget())
        self.assertTrue(panel.websocket_url.isReadOnly())
        self.assertEqual(
            panel.websocket_url.text(), "ws://mac.local:8765/ws/tracking"
        )
        panel.source.setCurrentIndex(panel.source.findData("video_file"))
        loop_states: list[bool] = []
        panel.playback.loopChanged.connect(loop_states.append)
        panel.playback.loop_button.click()
        self.assertTrue(panel.playback.loop_button.isChecked())
        panel.playback.loop_button.click()
        self.assertFalse(panel.playback.loop_button.isChecked())
        self.assertEqual(loop_states, [True, False])

    def test_models_page_has_detection_and_reid_model_selectors(self) -> None:
        window = self._window()
        try:
            models = window.panels["models"]
            tracking = window.panels["tracking"]
            benchmark = window.panels["benchmark"]
            self.assertGreaterEqual(models.detector_model.count(), 5)
            self.assertGreaterEqual(models.reid_model.count(), 5)
            self.assertTrue(str(models.detector_model.currentData()).endswith(".pt"))
            self.assertTrue(str(models.reid_model.currentData()).endswith("-reid.onnx"))
            self.assertFalse(hasattr(tracking, "detector_model"))
            self.assertEqual(
                benchmark.model_table.rowCount(),
                models.detector_model.count() * models.reid_model.count(),
            )
            self.assertEqual(
                window.controller.input_config.model_path,
                str(models.detector_model.currentData()),
            )
        finally:
            window.close()

    def test_linked_detection_model_persists_and_appears_in_benchmark(self) -> None:
        settings_path = self.root / "linked-model.ini"
        external_model = self.root / "custom-detector.onnx"
        external_model.touch()
        first = self._window(settings_path)
        try:
            first.panels["models"].link_detector_path(external_model)
            self.qt_app.processEvents()
            benchmark_paths = {
                str(
                    first.panels["benchmark"]
                    .model_table.item(row, 1)
                    .data(Qt.ItemDataRole.UserRole)
                )
                for row in range(first.panels["benchmark"].model_table.rowCount())
            }
            self.assertIn(str(external_model.resolve()), benchmark_paths)
        finally:
            first.close()
            self.qt_app.processEvents()

        second = self._window(settings_path)
        try:
            models = second.panels["models"]
            self.assertGreaterEqual(
                models.detector_model.findData(str(external_model.resolve())),
                0,
            )
            self.assertEqual(
                str(models.detector_model.currentData()),
                str(external_model.resolve()),
            )
        finally:
            second.close()

    def test_benchmark_setup_is_a_two_by_two_grid(self) -> None:
        window = self._window()
        try:
            benchmark = window.panels["benchmark"]
            grid = benchmark.setup_grid
            self.assertEqual(grid.count(), 4)
            self.assertIsNotNone(grid.itemAtPosition(0, 0))
            self.assertIsNotNone(grid.itemAtPosition(0, 1))
            self.assertIsNotNone(grid.itemAtPosition(1, 0))
            self.assertIsNotNone(grid.itemAtPosition(1, 1))
            self.assertEqual(
                benchmark.result_table.horizontalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
            )
            self.assertEqual(
                benchmark.result_table.verticalScrollBarPolicy(),
                Qt.ScrollBarPolicy.ScrollBarAlwaysOn,
            )
            self.assertEqual(benchmark.mode.currentData(), "quick_auto")
            self.assertFalse(benchmark.annotation_path.isEnabled())
            self.assertEqual(benchmark.rounds.value(), 3)
            self.assertEqual(benchmark.feature_limit.value(), 50)
            benchmark.output_dir = self.root / "benchmarks"
            recording = benchmark.output_dir / "live-test" / "source.mp4"
            recording.parent.mkdir(parents=True, exist_ok=True)
            recording.touch()
            benchmark._use_latest_recording()
            self.assertEqual(benchmark.video_path.text(), str(recording))
        finally:
            window.close()

    def test_tracking_help_matches_available_profiles_and_track_shot_modes(self) -> None:
        window = self._window()
        try:
            tracking = window.panels["tracking"]
            track_shot = window.panels["track_shot"]
            self.assertIn("640px", tracking.profile.toolTip())
            self.assertEqual(
                [
                    track_shot.mode.itemText(index)
                    for index in range(track_shot.mode.count())
                ],
                ["AI Tracking", "Fixed Cut", "In/Out Auto"],
            )
        finally:
            window.close()

    def test_feature_manager_uses_responsive_extended_icon_selection(self) -> None:
        snapshots = [
            SimpleNamespace(
                feature_id=index,
                frame_index=index * 10,
                quality_score=0.9,
                created_at=1_700_000_000.0,
                crop_jpeg=None,
            )
            for index in range(1, 6)
        ]
        dialog = FeatureManagerDialog(2, "2", lambda _gid: snapshots, lambda *_: 0)

        self.assertEqual(
            dialog.gallery.selectionMode(),
            dialog.gallery.SelectionMode.ExtendedSelection,
        )
        self.assertEqual(dialog.gallery.viewMode(), dialog.gallery.ViewMode.IconMode)
        self.assertTrue(dialog.gallery.isWrapping())
        self.assertEqual(dialog.gallery.resizeMode(), dialog.gallery.ResizeMode.Adjust)
        self.assertEqual(dialog.delete_button.text(), "Delete Feature")
        self.assertEqual(dialog.gallery.count(), 5)

    def test_qt_run_starts_iphone_server_automatically(self) -> None:
        class FakeController:
            def __init__(self) -> None:
                self.started = 0
                self.input_config = SimpleNamespace(source_type="iphone")

            def start(self) -> None:
                self.started += 1

        class FakeApplication:
            def processEvents(self) -> None:
                pass

            def exec(self) -> int:
                return 0

        controller = FakeController()
        window = SimpleNamespace(
            controller=controller,
            show=lambda: None,
        )

        result = BootstrappedQtDesktop(FakeApplication(), window).run()

        self.assertEqual(result, 0)
        self.assertEqual(controller.started, 1)


if __name__ == "__main__":
    unittest.main()
