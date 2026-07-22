"""Bounded latest-frame receiver for the iPhone JPEG camera stream."""

from __future__ import annotations

from threading import Lock
from time import monotonic, time
from typing import Any, Callable

from autocamtracker.core.timestamps import (
    FrameTimeline,
    TimestampMark,
    TimestampStage,
)
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
        self._decoded_frame_count = 0
        self._receive_sequence_gaps = 0
        self._receive_overwritten_frames = 0
        self._decode_failures = 0
        self._last_source_frame_id: int | None = None

    def accept(self, data: bytes) -> bool:
        unpacked = unpack_camera_frame(data)
        if unpacked is None:
            return False
        jpeg, capture_timestamp_ms, source_frame_id = unpacked
        received_at = monotonic()
        received_wall_time_ms = time() * 1000.0
        with self._lock:
            self._received_frame_count += 1
            frame_count = self._received_frame_count
            if (
                source_frame_id is not None
                and self._last_source_frame_id is not None
                and source_frame_id > self._last_source_frame_id + 1
            ):
                self._receive_sequence_gaps += source_frame_id - self._last_source_frame_id - 1
            if source_frame_id is not None:
                self._last_source_frame_id = source_frame_id
            if self._latest_frame_bytes is not None:
                self._receive_overwritten_frames += 1
            self._latest_frame_bytes = jpeg
            self._latest_frame_info = {
                "frame_count": frame_count,
                "source_frame_id": source_frame_id,
                "frame_bytes": len(jpeg),
                "capture_timestamp_ms": capture_timestamp_ms,
                "received_timestamp_ms": received_wall_time_ms,
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
        decoded_started_wall_time_ms = time() * 1000.0
        frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        decoded_at = monotonic()
        decoded_wall_time_ms = time() * 1000.0
        capture_timestamp_ms = info.get("capture_timestamp_ms")
        if frame is None:
            with self._lock:
                self._decode_failures += 1
            self._emit("camera_frame_decode_failed", source_frame_id=info.get("source_frame_id"))
            return None
        with self._lock:
            self._decoded_frame_count += 1
        timeline = FrameTimeline(
            frame_id=int(info.get("source_frame_id") or info.get("frame_count") or 0),
            source_id="iphone",
            capture_timestamp_ms=(
                float(capture_timestamp_ms) if capture_timestamp_ms is not None else None
            ),
        )
        timeline.mark(
            TimestampStage.RECEIVED,
            TimestampMark(
                float(info["received_timestamp_ms"]),
                float(info["received_monotonic_s"]) * 1000.0,
            ),
        )
        timeline.mark(
            TimestampStage.DECODE_STARTED,
            TimestampMark(decoded_started_wall_time_ms, decoded_started_at * 1000.0),
        )
        timeline.mark(
            TimestampStage.DECODE_COMPLETED,
            TimestampMark(decoded_wall_time_ms, decoded_at * 1000.0),
        )
        receive_latency_ms = None
        if capture_timestamp_ms is not None:
            transport_ms = float(info["received_timestamp_ms"]) - float(
                capture_timestamp_ms
            )
            if 0.0 <= transport_ms <= timeline.max_transport_latency_ms:
                receive_latency_ms = transport_ms
        timing = {
            **info,
            "stream_counters": self.stream_counters(),
            "decode_time_ms": (decoded_at - decoded_started_at) * 1000.0,
            "receive_latency_ms": receive_latency_ms,
            "decoded_monotonic_s": decoded_at,
            "decoded_timestamp_ms": decoded_wall_time_ms,
            "timeline": timeline,
        }
        with self._lock:
            self._latest_decoded_frame_info = timing
        return frame

    def latest_frame_timing(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._latest_decoded_frame_info)

    def stream_counters(self) -> dict[str, int]:
        with self._lock:
            return {
                "received": self._received_frame_count,
                "decoded": self._decoded_frame_count,
                "source_sequence_gaps": self._receive_sequence_gaps,
                "receive_overwritten": self._receive_overwritten_frames,
                "decode_failed": self._decode_failures,
            }

    def _emit(self, event: str, **fields: Any) -> None:
        if self.on_event is not None:
            self.on_event(event, fields)
