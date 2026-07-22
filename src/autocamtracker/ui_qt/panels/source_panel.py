from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
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
        self.connection = QLabel("iPhone link: idle")
        self.camera_index = QSpinBox()
        self.camera_index.setRange(0, 16)
        self.video_path = QLineEdit()
        self.video_path.setPlaceholderText("Choose a local video…")
        choose_video = QPushButton("Browse Video…")
        self.video_url = QLineEdit()
        self.video_url.setPlaceholderText("https://…")
        apply_url = QPushButton("Apply URL")
        self.screen_region = QLineEdit()
        self.screen_region.setPlaceholderText("left,top,width,height")
        apply_region = QPushButton("Apply Region")
        test_button = QPushButton("Test Connection")
        self.form.addRow("Input", self.source)
        self.form.addRow("Webcam index", self.camera_index)
        self.form.addRow(self.video_path)
        self.form.addRow(choose_video)
        self.form.addRow("Video URL", self.video_url)
        self.form.addRow(apply_url)
        self.form.addRow("Screen region", self.screen_region)
        self.form.addRow(apply_region)
        self.form.addRow(self.connection)
        self.form.addRow(test_button)
        self.source.currentIndexChanged.connect(
            lambda _index: self.sourceChanged.emit(str(self.source.currentData()))
        )
        test_button.clicked.connect(self.testConnectionRequested)
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
