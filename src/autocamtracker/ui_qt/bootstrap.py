"""Composition adapter for the parallel Qt process."""

from __future__ import annotations

from dataclasses import dataclass
import os
import sys
from typing import Sequence

from PySide6.QtWidgets import QApplication

from autocamtracker.bootstrap import build_dependencies
from autocamtracker.product import APP_NAME, DISPLAY_NAME
from autocamtracker.ui.app import AppConfig
from autocamtracker.ui_qt.main_window import AIVisionDirectorMainWindow


@dataclass(frozen=True)
class BootstrappedQtDesktop:
    application: QApplication
    window: AIVisionDirectorMainWindow
    edge_agent: object | None = None

    def run(self) -> int:
        self.window.show()
        if self.window.controller.input_config.source_type == "iphone":
            self.application.processEvents()
            self.window.controller.start()
        try:
            return self.application.exec()
        finally:
            if self.edge_agent is not None:
                self.edge_agent.stop()


def bootstrap(
    *,
    config: AppConfig | None = None,
    argv: Sequence[str] | None = None,
) -> BootstrappedQtDesktop:
    arguments = list(sys.argv if argv is None else argv)
    application = QApplication.instance() or QApplication(arguments)
    application.setApplicationName(APP_NAME)
    application.setApplicationDisplayName(DISPLAY_NAME)
    application.setOrganizationName(APP_NAME)
    app_config = config or AppConfig()
    dependencies = build_dependencies(app_config)
    window = AIVisionDirectorMainWindow(app_config, dependencies)
    edge_agent = None
    if os.environ.get("AIVD_EDGE_DEVICE_TOKEN") and os.environ.get(
        "AIVD_CONTROL_API_URL"
    ):
        from autocamtracker.edge_control.agent import ControlApiClient, EdgeAgent
        from autocamtracker.edge_control.qt_adapter import QtControlPort

        edge_agent = EdgeAgent(
            ControlApiClient(
                os.environ["AIVD_CONTROL_API_URL"],
                os.environ.get("AIVD_EDGE_NODE_ID", "edge-mac-01"),
                os.environ["AIVD_EDGE_DEVICE_TOKEN"],
            ),
            QtControlPort(window.controller),
        )
        edge_agent.start()
    file_arguments = arguments[1:] if argv is None else arguments
    if file_arguments:
        dependencies.application.input_config.source_type = "video_file"
        dependencies.application.input_config.video_path = file_arguments[0]
    return BootstrappedQtDesktop(application, window, edge_agent)


def run(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(bootstrap(argv=argv).run())
