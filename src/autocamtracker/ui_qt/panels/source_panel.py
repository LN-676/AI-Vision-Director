import os
from urllib.parse import urlsplit

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QWidget,
)

from autocamtracker.ui_qt.panels.base import FormPanel
from autocamtracker.ui_qt.panels.playback_panel import PlaybackPanel


def tablet_remote_url(websocket_url: str, lan_host: str | None = None) -> str:
    """Return the tablet console URL for the active launcher/network."""

    host = (lan_host or "").strip()
    if not host:
        host = urlsplit(websocket_url).hostname or ""
    if not host:
        return ""
    formatted_host = f"[{host}]" if ":" in host else host
    return f"http://{formatted_host}:3000/remote"


class SourcePanel(FormPanel):
    sourceChanged = Signal(str)
    testConnectionRequested = Signal()
    videoFileChanged = Signal(str)
    videoUrlChanged = Signal(str)
    cameraIndexChanged = Signal(int)
    screenRegionChanged = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.source = QComboBox()
        self.source.addItem("iPhone", "iphone")
        self.source.addItem("Webcam", "webcam")
        self.source.addItem("Video file", "video_file")
        self.source.addItem("Video URL", "video_url")
        self.source.addItem("Screen region", "screen_region")
        self.pages = QStackedWidget()
        self.pages.setMinimumWidth(0)
        self.pages.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

        iphone_page = QWidget()
        iphone_page.setMinimumWidth(0)
        iphone_form = QFormLayout(iphone_page)
        self.websocket_url = QLineEdit()
        self.websocket_url.setMinimumWidth(0)
        self.websocket_url.setReadOnly(True)
        self.websocket_url.setPlaceholderText("Start the desktop link to show its URL")
        self.tablet_url = QLineEdit()
        self.tablet_url.setMinimumWidth(0)
        self.tablet_url.setReadOnly(True)
        self.tablet_url.setPlaceholderText(
            "Start the Remote Console to show its URL"
        )
        self.tablet_url.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.connection = QLabel("iPhone link: idle")
        self.connection.setWordWrap(True)
        self.connection.setMinimumWidth(0)
        self.connection.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.copy_websocket_url_button = QPushButton("Copy WebSocket URL")
        self.copy_tablet_url_button = QPushButton("Copy Tablet URL")
        tablet_url_row = QWidget()
        tablet_url_layout = QHBoxLayout(tablet_url_row)
        tablet_url_layout.setContentsMargins(0, 0, 0, 0)
        tablet_url_layout.addWidget(self.tablet_url, 1)
        tablet_url_layout.addWidget(self.copy_tablet_url_button)
        test_button = QPushButton("Start / Test iPhone Connection")
        iphone_form.addRow("WebSocket URL", self.websocket_url)
        iphone_form.addRow(self.copy_websocket_url_button)
        iphone_form.addRow(self.connection)
        iphone_form.addRow(test_button)
        iphone_form.addRow("Tablet Remote URL", tablet_url_row)

        webcam_page = QWidget()
        webcam_form = QFormLayout(webcam_page)
        self.camera_index = QSpinBox()
        self.camera_index.setRange(0, 16)
        webcam_form.addRow("Webcam index", self.camera_index)

        video_file_page = QWidget()
        video_file_form = QFormLayout(video_file_page)
        self.video_path = QLineEdit()
        self.video_path.setPlaceholderText("Choose a local video…")
        choose_video = QPushButton("Browse Video…")
        self.playback = PlaybackPanel()
        video_file_form.addRow("Video file", self.video_path)
        video_file_form.addRow(choose_video)
        video_file_form.addRow(self.playback)

        video_url_page = QWidget()
        video_url_form = QFormLayout(video_url_page)
        self.video_url = QLineEdit()
        self.video_url.setPlaceholderText("https://…")
        apply_url = QPushButton("Apply URL")
        video_url_form.addRow("Video URL", self.video_url)
        video_url_form.addRow(apply_url)

        screen_page = QWidget()
        screen_form = QFormLayout(screen_page)
        self.screen_region = QLineEdit()
        self.screen_region.setPlaceholderText("left,top,width,height")
        apply_region = QPushButton("Apply Region")
        screen_form.addRow("Screen region", self.screen_region)
        screen_form.addRow(apply_region)

        for page in (
            iphone_page,
            webcam_page,
            video_file_page,
            video_url_page,
            screen_page,
        ):
            self.pages.addWidget(page)
        self.form.addRow("Input", self.source)
        self.form.addRow(self.pages)
        self.source.currentIndexChanged.connect(self._source_selected)
        test_button.clicked.connect(self.testConnectionRequested)
        self.copy_websocket_url_button.clicked.connect(
            self._copy_websocket_url
        )
        self.copy_tablet_url_button.clicked.connect(self._copy_tablet_url)
        choose_video.clicked.connect(self._choose_video)
        apply_url.clicked.connect(lambda: self.videoUrlChanged.emit(self.video_url.text().strip()))
        apply_region.clicked.connect(
            lambda: self.screenRegionChanged.emit(self.screen_region.text().strip())
        )
        self.camera_index.valueChanged.connect(self.cameraIndexChanged)

    def _choose_video(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose video file",
            "",
            "Video files (*.mp4 *.mov *.avi *.mkv);;All files (*)",
        )
        if path:
            self.video_path.setText(path)
            self.source.setCurrentIndex(self.source.findData("video_file"))
            self.videoFileChanged.emit(path)

    def set_connection(self, text: str) -> None:
        self.connection.setText(text)

    def set_iphone_url(self, url: str) -> None:
        self.websocket_url.setText(url)
        self.websocket_url.setCursorPosition(0)
        self.websocket_url.setToolTip(url)
        self.set_tablet_url(
            tablet_remote_url(url, os.environ.get("AIVD_LAN_HOST"))
        )

    def set_tablet_url(self, url: str) -> None:
        self.tablet_url.setText(url)
        self.tablet_url.setCursorPosition(0)
        self.tablet_url.setToolTip(url)

    def _source_selected(self, index: int) -> None:
        self.pages.setCurrentIndex(max(0, index))
        self.sourceChanged.emit(str(self.source.currentData()))

    def _copy_websocket_url(self) -> None:
        url = self.websocket_url.text().strip()
        if url:
            QGuiApplication.clipboard().setText(url)

    def _copy_tablet_url(self) -> None:
        url = self.tablet_url.text().strip()
        if url:
            QGuiApplication.clipboard().setText(url)
