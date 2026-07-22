"""Composition adapter for the parallel Qt process."""

from __future__ import annotations

from dataclasses import dataclass
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

    def run(self) -> int:
        if self.window.controller.input_config.source_type == "iphone":
            self.window.dependencies.tracking_server.start()
        self.window.show()
        return self.application.exec()


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
    file_arguments = arguments[1:] if argv is None else arguments
    if file_arguments:
        dependencies.application.input_config.source_type = "video_file"
        dependencies.application.input_config.video_path = file_arguments[0]
    return BootstrappedQtDesktop(application, window)


def run(argv: Sequence[str] | None = None) -> None:
    raise SystemExit(bootstrap(argv=argv).run())
