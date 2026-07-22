"""Scheme A dockable PySide6 main window."""

from __future__ import annotations

from queue import Empty

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QTabWidget

from autocamtracker.product import DISPLAY_NAME
from autocamtracker.ui_qt.actions import create_workspace_actions
from autocamtracker.ui_qt.controller import QtRuntimeController
from autocamtracker.ui_qt.panels import (
    DiagnosticsPanel,
    PerformancePanel,
    SourcePanel,
    TrackShotPanel,
    TrackingPanel,
    VehicleDatabasePanel,
)
from autocamtracker.ui_qt.panels.feature_manager_dialog import FeatureManagerDialog
from autocamtracker.ui_qt.state import (
    APPLICATION_NAME,
    CUSTOM_GEOMETRY_KEY,
    CUSTOM_SPLITTER_KEY,
    CUSTOM_STATE_KEY,
    GEOMETRY_KEY,
    LAYOUT_VERSION,
    ORGANIZATION_NAME,
    PRESET_KEY,
    SOURCE_KEY,
    SPLITTER_KEY,
    STATE_KEY,
    VERSION_KEY,
    Workspace,
)
from autocamtracker.ui_qt.widgets import DualMonitorWidget


class AIVisionDirectorMainWindow(QMainWindow):
    """Balanced dual-monitor workspace backed by existing application services."""

    def __init__(self, config, dependencies, *, settings: QSettings | None = None, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.dependencies = dependencies
        self.settings = settings or QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self.setObjectName("main.aiVisionDirector")
        self.setWindowTitle(DISPLAY_NAME)
        self.setMinimumSize(1120, 720)
        self.resize(1440, 900)
        self.setStyleSheet(
            "QMainWindow::separator { width: 12px; height: 12px; "
            "background: transparent; } "
            "QMainWindow::separator:hover { background: #4f7cac; }"
        )
        self.setDockOptions(
            QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
            | QMainWindow.DockOption.GroupedDragging
        )
        self.setTabPosition(
            Qt.DockWidgetArea.AllDockWidgetAreas, QTabWidget.TabPosition.North
        )

        self.monitors = DualMonitorWidget(self)
        self.setCentralWidget(self.monitors)
        self.controller = QtRuntimeController(config, dependencies, self)
        saved_source = str(
            self.settings.value(SOURCE_KEY, self.controller.input_config.source_type)
        )
        if saved_source in {
            "iphone",
            "webcam",
            "video_file",
            "video_url",
            "screen_region",
        }:
            self.controller.input_config.source_type = saved_source
        self.panels = self._create_panels()
        self.docks = self._create_docks()
        self._monitor_maximized = False
        self._dock_visibility_before_maximize: dict[str, bool] = {}
        self._status_bar_was_visible = True
        self.workspace_actions = create_workspace_actions(self, self.apply_workspace)
        self._create_menus()
        self._create_status_bar()
        self._connect_panels()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._refresh_status_panels)
        self._status_timer.start()
        self.restore_workspace()
        self.controller.refresh_vehicles()

    def _create_panels(self) -> dict[str, object]:
        return {
            "source": SourcePanel(),
            "tracking": TrackingPanel(
                self.config.model_dir,
                self.config.default_model,
                self.config.default_reid_model,
            ),
            "track_shot": TrackShotPanel(),
            "vehicle_database": VehicleDatabasePanel(),
            "performance": PerformancePanel(),
            "diagnostics": DiagnosticsPanel(),
        }

    def _create_docks(self) -> dict[str, QDockWidget]:
        titles = {
            "source": "Source",
            "tracking": "Tracking",
            "track_shot": "Track Shot",
            "vehicle_database": "Vehicle Database",
            "performance": "Performance",
            "diagnostics": "Diagnostics",
        }
        docks: dict[str, QDockWidget] = {}
        for key, panel in self.panels.items():
            dock = QDockWidget(titles[key], self)
            dock.setObjectName(f"dock.{key}")
            dock.setWidget(panel)
            dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
            dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetClosable
                | QDockWidget.DockWidgetFeature.DockWidgetMovable
                | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            )
            if key in {"source", "tracking"}:
                dock.setMinimumWidth(260)
            elif key == "vehicle_database":
                dock.setMinimumWidth(300)
            if key in {"performance", "diagnostics"}:
                dock.topLevelChanged.connect(
                    lambda floating, item=dock: item.setMinimumSize(
                        720 if floating else 0, 480 if floating else 0
                    )
                )
            docks[key] = dock
        return docks

    def _create_menus(self) -> None:
        window_menu = self.menuBar().addMenu("Window")
        self.maximize_monitors_action = QAction("Maximize Monitors", self)
        self.maximize_monitors_action.setCheckable(True)
        self.maximize_monitors_action.setShortcut("Ctrl+Shift+M")
        self.maximize_monitors_action.triggered.connect(self.toggle_monitor_maximize)
        window_menu.addAction(self.maximize_monitors_action)
        window_menu.addSeparator()
        panels_menu = window_menu.addMenu("Panels")
        for key in (
            "source",
            "tracking",
            "track_shot",
            "vehicle_database",
            "performance",
            "diagnostics",
        ):
            panels_menu.addAction(self.docks[key].toggleViewAction())
        workspace_menu = window_menu.addMenu("Workspace")
        for workspace in Workspace:
            workspace_menu.addAction(self.workspace_actions[workspace])
        workspace_menu.addSeparator()
        save_custom_action = QAction("Custom Layout — Save Current", self)
        save_custom_action.setShortcut("Ctrl+4")
        save_custom_action.triggered.connect(self.save_custom_workspace)
        workspace_menu.addAction(save_custom_action)
        restore_custom_action = QAction("Restore Custom Layout", self)
        restore_custom_action.triggered.connect(self.restore_custom_workspace)
        workspace_menu.addAction(restore_custom_action)
        workspace_menu.addSeparator()
        reset_action = QAction("Reset Workspace", self)
        reset_action.setShortcut("Ctrl+Shift+0")
        reset_action.triggered.connect(self.reset_workspace)
        workspace_menu.addAction(reset_action)

    def _create_status_bar(self) -> None:
        self.status_label = QLabel("Status: idle")
        self.iphone_label = QLabel("iPhone link: idle")
        self.fps_label = QLabel("FPS: 0.0")
        self.inference_label = QLabel("Inference: 0.0 ms")
        status = self.statusBar()
        status.addWidget(self.status_label, 1)
        status.addPermanentWidget(self.iphone_label)
        status.addPermanentWidget(self.fps_label)
        status.addPermanentWidget(self.inference_label)

    def _connect_panels(self) -> None:
        source: SourcePanel = self.panels["source"]
        tracking: TrackingPanel = self.panels["tracking"]
        track_shot: TrackShotPanel = self.panels["track_shot"]
        playback = source.playback
        database: VehicleDatabasePanel = self.panels["vehicle_database"]

        source.sourceChanged.connect(self._source_changed)
        source.videoFileChanged.connect(self.controller.set_video_file)
        source.videoUrlChanged.connect(self.controller.set_video_url)
        source.cameraIndexChanged.connect(self.controller.set_camera_index)
        source.screenRegionChanged.connect(self.controller.set_screen_region)
        source.testConnectionRequested.connect(self._test_connection)
        tracking.autoTrackRequested.connect(self.controller.auto_track)
        tracking.clearRequested.connect(self.controller.clear_selection)
        tracking.resetRequested.connect(self.controller.reset_tracking)
        tracking.framingChanged.connect(self.controller.set_framing)
        tracking.configurationChanged.connect(self.controller.configure_tracking)
        tracking.detectorModelChanged.connect(self.controller.set_detector_model)
        tracking.reidModelChanged.connect(self.controller.set_reid_model)
        track_shot.modeChanged.connect(self.controller.set_track_shot_mode)
        track_shot.rearmRequested.connect(self.controller.rearm_track_shot)
        playback.startRequested.connect(self.controller.start)
        playback.pauseRequested.connect(self.controller.pause)
        playback.stopRequested.connect(self.controller.stop)
        playback.recordRequested.connect(self.controller.toggle_recording)
        playback.speedChanged.connect(self.controller.set_playback_speed)
        playback.loopChanged.connect(self.controller.set_loop_enabled)
        database.addRequested.connect(self.controller.add_vehicle)
        database.linkRequested.connect(self.controller.link_vehicle)
        database.findRequested.connect(self.controller.find_vehicle)
        database.releaseRequested.connect(self.controller.release_vehicle)
        database.deleteRequested.connect(self.controller.delete_vehicle)
        database.previewRequested.connect(self._show_feature_preview)
        database.manageFeaturesRequested.connect(self._open_feature_manager)
        database.findThresholdChanged.connect(self.controller.set_find_threshold)
        database.manualFeatureRequested.connect(self.controller.add_manual_feature)
        database.autoFeatureRequested.connect(self.controller.toggle_auto_feature)
        self.monitors.before_view.frameClicked.connect(self.controller.select_at)

        self.controller.beforeFrameReady.connect(self.monitors.before_view.set_frame)
        self.controller.afterFrameReady.connect(self.monitors.after_view.set_frame)
        self.controller.statusChanged.connect(
            lambda text: self.status_label.setText(f"Status: {text}")
        )
        self.controller.fpsChanged.connect(
            lambda value: self.fps_label.setText(f"FPS: {value:.1f}")
        )
        self.controller.inferenceChanged.connect(
            lambda value: self.inference_label.setText(f"Inference: {value:.1f} ms")
        )
        self.controller.vehiclesChanged.connect(database.set_vehicles)
        self.controller.timelineChanged.connect(self._update_timeline)
        self.controller.metricsChanged.connect(self.monitors.set_metrics)
        self.monitors.before_view.doubleClicked.connect(
            lambda: self.toggle_monitor_maximize()
        )
        self.monitors.after_view.doubleClicked.connect(
            lambda: self.toggle_monitor_maximize()
        )

        playback.timeline.sliderReleased.connect(
            lambda: self.controller.seek(playback.timeline.value())
        )
        source.source.setCurrentIndex(
            source.source.findData(self.controller.input_config.source_type)
        )
        self.controller.configure_tracking(
            tracking.profile.currentText(),
            tracking.tracker.currentText(),
            tracking.confidence.value(),
        )
        self.controller.set_detector_model(str(tracking.detector_model.currentData() or ""))
        self.controller.set_reid_model(str(tracking.reid_model.currentData() or ""))
        database.find_threshold.setValue(
            self.controller.application.identity_manager.auto_reid_min_score
        )
        source.set_iphone_url(self.dependencies.tracking_server.preferred_url)

    def _update_timeline(self, maximum: int, value: int, fps: float) -> None:
        self.panels["source"].playback.set_timeline(maximum, value, fps)

    def toggle_monitor_maximize(self, checked: bool | None = None) -> None:
        maximize = not self._monitor_maximized if checked is None else bool(checked)
        if maximize == self._monitor_maximized:
            return
        if maximize:
            self._dock_visibility_before_maximize = {
                key: dock.isVisible() for key, dock in self.docks.items()
            }
            self._status_bar_was_visible = self.statusBar().isVisible()
            for dock in self.docks.values():
                dock.hide()
            self.statusBar().hide()
        else:
            for key, dock in self.docks.items():
                dock.setVisible(self._dock_visibility_before_maximize.get(key, True))
            self.statusBar().setVisible(self._status_bar_was_visible)
        self._monitor_maximized = maximize
        self.maximize_monitors_action.setChecked(maximize)

    def apply_workspace(self, workspace: Workspace) -> None:
        if self._monitor_maximized:
            self.toggle_monitor_maximize(False)
        if not isinstance(workspace, Workspace):
            workspace = Workspace(workspace)
        self._install_default_docks()
        for dock in self.docks.values():
            dock.show()
        if workspace == Workspace.IDENTITY:
            self.docks["source"].hide()
            self.docks["diagnostics"].hide()
            self.docks["performance"].hide()
            self.monitors.splitter.setSizes([1, 2])
            self.docks["vehicle_database"].raise_()
        elif workspace == Workspace.PERFORMANCE:
            self.docks["source"].hide()
            self.docks["tracking"].hide()
            self.docks["track_shot"].hide()
            self.docks["vehicle_database"].hide()
            self.monitors.splitter.setSizes([1, 1])
            self.docks["performance"].raise_()
            self.resizeDocks(
                [self.docks["performance"], self.docks["diagnostics"]],
                [480, 480],
                Qt.Orientation.Vertical,
            )
        else:
            self.docks["performance"].hide()
            self.monitors.splitter.setSizes([1, 1])
            self.docks["tracking"].raise_()
            self.docks["vehicle_database"].raise_()
        self.workspace_actions[workspace].setChecked(True)
        self.settings.setValue(PRESET_KEY, workspace.value)

    def _install_default_docks(self) -> None:
        for dock in self.docks.values():
            dock.setFloating(False)
            self.removeDockWidget(dock)
        for key in ("source", "tracking", "track_shot"):
            self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.docks[key])
        self.tabifyDockWidget(self.docks["source"], self.docks["tracking"])
        self.tabifyDockWidget(self.docks["tracking"], self.docks["track_shot"])
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.docks["vehicle_database"]
        )
        for key in ("performance", "diagnostics"):
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.docks[key])
        self.tabifyDockWidget(self.docks["performance"], self.docks["diagnostics"])

    def save_workspace(self) -> None:
        self.settings.setValue(VERSION_KEY, LAYOUT_VERSION)
        self.settings.setValue(GEOMETRY_KEY, self.saveGeometry())
        self.settings.setValue(STATE_KEY, self.saveState(LAYOUT_VERSION))
        self.settings.setValue(SPLITTER_KEY, self.monitors.splitter.saveState())
        self.settings.sync()

    def save_custom_workspace(self) -> None:
        if self._monitor_maximized:
            self.toggle_monitor_maximize(False)
        self.settings.setValue(CUSTOM_GEOMETRY_KEY, self.saveGeometry())
        self.settings.setValue(CUSTOM_STATE_KEY, self.saveState(LAYOUT_VERSION))
        self.settings.setValue(
            CUSTOM_SPLITTER_KEY, self.monitors.splitter.saveState()
        )
        self.save_workspace()
        self.status_label.setText("Status: custom layout saved")

    def restore_custom_workspace(self) -> bool:
        geometry = self.settings.value(CUSTOM_GEOMETRY_KEY, QByteArray())
        state = self.settings.value(CUSTOM_STATE_KEY, QByteArray())
        splitter = self.settings.value(CUSTOM_SPLITTER_KEY, QByteArray())
        if not geometry or not state:
            self.status_label.setText("Status: no custom layout has been saved")
            return False
        geometry_ok = self.restoreGeometry(geometry)
        state_ok = self.restoreState(state, LAYOUT_VERSION)
        splitter_ok = bool(splitter) and self.monitors.splitter.restoreState(splitter)
        restored = bool(geometry_ok and state_ok and splitter_ok)
        self.status_label.setText(
            "Status: custom layout restored"
            if restored
            else "Status: custom layout could not be restored"
        )
        return restored

    def restore_workspace(self) -> bool:
        version = int(self.settings.value(VERSION_KEY, 0))
        if version != LAYOUT_VERSION:
            self.reset_workspace()
            return False
        geometry = self.settings.value(GEOMETRY_KEY, QByteArray())
        state = self.settings.value(STATE_KEY, QByteArray())
        splitter = self.settings.value(SPLITTER_KEY, QByteArray())
        geometry_ok = bool(geometry) and self.restoreGeometry(geometry)
        state_ok = bool(state) and self.restoreState(state, LAYOUT_VERSION)
        splitter_ok = bool(splitter) and self.monitors.splitter.restoreState(splitter)
        try:
            workspace = Workspace(str(self.settings.value(PRESET_KEY, Workspace.TRACKING.value)))
        except ValueError:
            workspace = Workspace.TRACKING
        self.workspace_actions[workspace].setChecked(True)
        if not state_ok:
            self.apply_workspace(workspace)
        return bool(geometry_ok and state_ok and splitter_ok)

    def reset_workspace(self) -> None:
        self.settings.remove(GEOMETRY_KEY)
        self.settings.remove(STATE_KEY)
        self.settings.remove(SPLITTER_KEY)
        self.settings.setValue(VERSION_KEY, LAYOUT_VERSION)
        self.resize(1440, 900)
        self.apply_workspace(Workspace.TRACKING)

    def _test_connection(self) -> None:
        self._source_changed("iphone")
        self.panels["source"].set_iphone_url(
            self.dependencies.tracking_server.preferred_url
        )
        self.status_label.setText("Status: iPhone connection service started")

    def _source_changed(self, source: str) -> None:
        self.settings.setValue(SOURCE_KEY, source)
        self.controller.configure_source(source)
        if source == "iphone":
            self.controller.start()

    def _show_feature_preview(self, gid: int) -> None:
        self.panels["vehicle_database"].show_feature_preview(
            gid, self.controller.first_feature_preview(gid)
        )

    def _open_feature_manager(self, gid: int) -> None:
        dialog = FeatureManagerDialog(
            gid,
            self.controller.vehicle_display_name(gid),
            self.controller.feature_snapshots,
            self.controller.rollback_features,
            self,
        )
        dialog.exec()

    def _refresh_status_panels(self) -> None:
        try:
            while True:
                message = self.dependencies.iphone_status_queue.get_nowait()
                text = f"iPhone link: {message}"
                self.iphone_label.setText(text)
                self.panels["source"].set_connection(text)
        except Empty:
            pass
        self.panels["source"].set_iphone_url(
            self.dependencies.tracking_server.preferred_url
        )
        self.panels["performance"].set_snapshot(
            self.dependencies.performance_evaluator.snapshot()
        )
        self.dependencies.diagnostics_service.observe_server(
            self.dependencies.tracking_server, False
        )
        self.panels["diagnostics"].set_health(
            self.dependencies.diagnostics_service.snapshot()
        )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._monitor_maximized:
            self.toggle_monitor_maximize(False)
        self.save_workspace()
        self._status_timer.stop()
        self.controller.close()
        event.accept()
