import os
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from autocamtracker.ui_qt.panels.source_panel import (
    SourcePanel,
    tablet_remote_url,
)


class TabletRemoteURLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication([])

    def test_uses_launcher_host_or_bonjour_fallback(self) -> None:
        websocket_url = "ws://mac-studio.local:8765/ws/tracking"

        self.assertEqual(
            tablet_remote_url(websocket_url),
            "http://mac-studio.local:3000/remote",
        )
        self.assertEqual(
            tablet_remote_url(websocket_url, "169.254.59.21"),
            "http://169.254.59.21:3000/remote",
        )

    def test_panel_updates_and_copies_tablet_url(self) -> None:
        with patch.dict(
            os.environ,
            {"AIVD_LAN_HOST": "172.20.10.2"},
        ):
            panel = SourcePanel()
            panel.set_iphone_url("ws://mac.local:8765/ws/tracking")

        self.assertTrue(panel.tablet_url.isReadOnly())
        self.assertEqual(
            panel.tablet_url.text(),
            "http://172.20.10.2:3000/remote",
        )
        panel.copy_tablet_url_button.click()
        self.assertEqual(
            QApplication.clipboard().text(),
            "http://172.20.10.2:3000/remote",
        )


if __name__ == "__main__":
    unittest.main()
