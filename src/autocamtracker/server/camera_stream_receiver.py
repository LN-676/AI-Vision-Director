"""Bounded latest-frame receiver for the iPhone JPEG camera stream."""

from __future__ import annotations

from threading import Lock
from time import monotonic, time
from typing import Any, Callable

from autocamtracker.server.protocol import unpack_camera_frame


class CameraStreamReceiver:
    def __init__(
        self,
        *,
        on_status: Callable[[str], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.on_status = on_status
        self.on_event = on_event
        self._lock = Lock()
        self._latest_frame_bytes: bytes | None = None
        self._latest_frame_info: dict[str, Any] = {}
        self._latest_decoded_frame_info: dict[str, Any] = {}
        self._received_frame_count = 0

    def accept(self, data: bytes) -> bool:
        unpacked = unpack_camera_frame(data)
        if unpacked is None:
            return False
        jpeg, capture_timestamp_ms = unpacked
        received_at = monotonic()
        with self._lock:
            self._received_frame_count += 1
            frame_count = self._received_frame_count
            self._latest_frame_bytes = jpeg
            self._latest_frame_info = {
                "frame_count": frame_count,
                "frame_bytes": len(jpeg),
                "capture_timestamp_ms": capture_timestamp_ms,
                "received_monotonic_s": received_at,
            }
        if frame_count == 1:
            self._emit("camera_frame_received", frame_bytes=len(jpeg), frame_count=frame_count)
            if self.on_status is not None:
                self.on_status("iPhone video receiving")
        elif frame_count % 150 == 0:
            self._emit("camera_frame_received", frame_bytes=len(jpeg), frame_count=frame_count)
        return True

    def read_latest_frame(self):
        """Decode and consume only the newest accepted JPEG frame."""

        with self._lock:
            data = self._latest_frame_bytes
            info = dict(self._latest_frame_info)
            self._latest_frame_bytes = None
        if data is None:
            return None

        import cv2
        import numpy as np

        decoded_started_at = monotonic()
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        decoded_at = monotonic()
        capture_timestamp_ms = info.get("capture_timestamp_ms")
        receive_latency_ms = None
        if capture_timestamp_ms is not None:
            receive_latency_ms = max(0.0, time() * 1000.0 - float(capture_timestamp_ms))
        timing = {
            **info,
            "decode_time_ms": (decoded_at - decoded_started_at) * 1000.0,
            "receive_latency_ms": receive_latency_ms,
            "decoded_monotonic_s": decoded_at,
        }
        with self._lock:
            self._latest_decoded_frame_info = timing
        return frame

    def latest_frame_timing(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest_decoded_frame_info)

    def _emit(self, event: str, **fields: Any) -> None:
        if self.on_event is not None:
            self.on_event(event, fields)
