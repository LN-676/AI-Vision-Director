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
from autocamtracker.ui_qt.panels.playback_panel import format_timecode
from autocamtracker.ui_qt.panels.source_panel import SourcePanel
from autocamtracker.ui_qt.panels.vehicle_database_panel import VehicleDatabasePanel
from autocamtracker.ui_qt.state import LAYOUT_VERSION, VERSION_KEY, Workspace
from autocamtracker.ui_qt.widgets.video_view import VideoView, qimage_from_bgr


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
        self.assertEqual(DISPLAY_NAME, "AI Vision Director V2.1")
        self.assertEqual(VERSION, "1.0")
        self.assertIs(AIVisonDirectorApp, AIVisionDirectorApp)
        self.assertIs(AutoCamTrackerApp, AIVisionDirectorApp)

    def test_main_window_smoke_and_unique_docks(self) -> None:
        window = self._window()
        try:
            window.show()
            self.qt_app.processEvents()
            names = [dock.objectName() for dock in window.docks.values()]
            self.assertEqual(window.windowTitle(), DISPLAY_NAME)
            self.assertEqual(len(names), 6)
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

    def test_tracking_page_has_detection_and_reid_model_selectors(self) -> None:
        window = self._window()
        try:
            tracking = window.panels["tracking"]
            self.assertGreaterEqual(tracking.detector_model.count(), 5)
            self.assertGreaterEqual(tracking.reid_model.count(), 5)
            self.assertTrue(str(tracking.detector_model.currentData()).endswith(".pt"))
            self.assertTrue(str(tracking.reid_model.currentData()).endswith("-reid.onnx"))
            self.assertEqual(
                window.controller.input_config.model_path,
                str(tracking.detector_model.currentData()),
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
