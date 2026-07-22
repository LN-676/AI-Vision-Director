from pathlib import Path
import tempfile
import unittest

import numpy as np
from PySide6.QtCore import QPointF, QSettings
from PySide6.QtWidgets import QApplication

from autocamtracker.bootstrap import build_dependencies
from autocamtracker.product import DISPLAY_NAME, VERSION
from autocamtracker.ui.app import (
    AIVisionDirectorApp,
    AIVisonDirectorApp,
    AppConfig,
    AutoCamTrackerApp,
)
from autocamtracker.ui_qt.controller import video_sync_plan
from autocamtracker.ui_qt.main_window import AIVisionDirectorMainWindow
from autocamtracker.ui_qt.panels.playback_panel import format_timecode
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
        self.assertEqual(DISPLAY_NAME, "AI Vision Director V2.0 beta1")
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
            self.assertEqual(len(names), 8)
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(window.monitors.before_view.minimumWidth(), 320)
            self.assertGreaterEqual(window.monitors.after_view.minimumHeight(), 232)
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


if __name__ == "__main__":
    unittest.main()
