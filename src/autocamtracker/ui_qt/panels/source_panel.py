from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QWidget,
)

from autocamtracker.ui_qt.panels.base import FormPanel


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

        iphone_page = QWidget()
        iphone_form = QFormLayout(iphone_page)
        self.websocket_url = QLineEdit()
        self.websocket_url.setReadOnly(True)
        self.websocket_url.setPlaceholderText("Start the desktop link to show its URL")
        self.connection = QLabel("iPhone link: idle")
        copy_url = QPushButton("Copy WebSocket URL")
        test_button = QPushButton("Start / Test iPhone Connection")
        iphone_form.addRow("WebSocket URL", self.websocket_url)
        iphone_form.addRow(copy_url)
        iphone_form.addRow(self.connection)
        iphone_form.addRow(test_button)

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
        video_file_form.addRow("Video file", self.video_path)
        video_file_form.addRow(choose_video)

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
        copy_url.clicked.connect(self._copy_websocket_url)
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

    def _source_selected(self, index: int) -> None:
        self.pages.setCurrentIndex(max(0, index))
        self.sourceChanged.emit(str(self.source.currentData()))

    def _copy_websocket_url(self) -> None:
        url = self.websocket_url.text().strip()
        if url:
            QGuiApplication.clipboard().setText(url)
