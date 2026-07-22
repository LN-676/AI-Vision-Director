"""Aspect-preserving video display and source-coordinate click mapping."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QWidget


def qimage_from_bgr(frame: Any) -> QImage:
    """Copy a numpy/OpenCV frame into an owned RGB QImage."""

    import numpy as np

    array = np.asarray(frame)
    if array.ndim == 2:
        contiguous = np.ascontiguousarray(array)
        height, width = contiguous.shape
        image = QImage(
            contiguous.data,
            width,
            height,
            int(contiguous.strides[0]),
            QImage.Format.Format_Grayscale8,
        )
        return image.copy()
    if array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValueError("frame must be HxW, HxWx3, or HxWx4")
    contiguous = np.ascontiguousarray(array)
    height, width, channels = contiguous.shape
    image_format = (
        QImage.Format.Format_BGR888
        if channels == 3
        else QImage.Format.Format_RGBA8888
    )
    image = QImage(
        contiguous.data,
        width,
        height,
        int(contiguous.strides[0]),
        image_format,
    )
    return image.copy().convertToFormat(QImage.Format.Format_RGB888)


class VideoView(QWidget):
    frameClicked = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setMouseTracking(True)
        self._pixmap = QPixmap()
        self._source_size = (0, 0)

    @property
    def source_size(self) -> tuple[int, int]:
        return self._source_size

    def set_frame(self, frame: Any) -> None:
        image = qimage_from_bgr(frame)
        self._source_size = (image.width(), image.height())
        self._pixmap = QPixmap.fromImage(image)
        self.update()

    def clear(self) -> None:
        self._pixmap = QPixmap()
        self._source_size = (0, 0)
        self.update()

    def image_rect(self) -> QRectF:
        if self._pixmap.isNull():
            return QRectF()
        scaled = self._pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - scaled.width()) / 2.0
        y = (self.height() - scaled.height()) / 2.0
        return QRectF(x, y, scaled.width(), scaled.height())

    def map_to_frame(self, point: QPointF) -> tuple[float, float] | None:
        rect = self.image_rect()
        if rect.isEmpty() or not rect.contains(point):
            return None
        source_width, source_height = self._source_size
        x = (point.x() - rect.left()) * source_width / rect.width()
        y = (point.y() - rect.top()) * source_height / rect.height()
        return (
            max(0.0, min(float(source_width), x)),
            max(0.0, min(float(source_height), y)),
        )

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#151a22"))
        if not self._pixmap.isNull():
            painter.drawPixmap(self.image_rect(), self._pixmap, QRectF(self._pixmap.rect()))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            mapped = self.map_to_frame(event.position())
            if mapped is not None:
                self.frameClicked.emit(*mapped)
        super().mousePressEvent(event)
