"""Versioned WebSocket wire protocol for the desktop and DockKit client."""

from __future__ import annotations

from dataclasses import dataclass
import json
from time import time
from typing import Any

from autocamtracker.product import VERSION


SOURCE_VERSION = VERSION
CAMERA_FRAME_ENVELOPE_MAGIC = b"ACTF1"
CAMERA_FRAME_ENVELOPE_HEADER_BYTES = len(CAMERA_FRAME_ENVELOPE_MAGIC) + 8
CAMERA_FRAME_ENVELOPE_V2_MAGIC = b"ACTF2"
CAMERA_FRAME_ENVELOPE_V2_HEADER_BYTES = len(CAMERA_FRAME_ENVELOPE_V2_MAGIC) + 16


@dataclass(frozen=True)
class MotorStatus:
    docked: bool
    manual_ready: bool
    system_tracking_enabled: bool | None
    last_error: str | None
    timestamp_ms: int
    current_velocity: dict[str, Any] | None = None
    last_command: dict[str, Any] | None = None
    last_stop_reason: str | None = None
    camera_zoom_factor: float | None = None
    camera_display_zoom_factor: float | None = None
    camera_frames_sent: int = 0
    camera_frames_dropped: int = 0

    @property
    def ready(self) -> bool:
        return self.docked and self.manual_ready and self.system_tracking_enabled is False


def encode_message(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"))


def decode_message(message: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(message)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def tracking_message(
    *,
    target_locked: bool,
    error_x: float = 0.0,
    error_y: float = 0.0,
    confidence: float = 0.0,
    target_id: int | None = None,
    sequence: int = 0,
    frame_width: int | None = None,
    frame_height: int | None = None,
    target_x: float | None = None,
    target_y: float | None = None,
    bbox_width: float | None = None,
    bbox_height: float | None = None,
    zoom_factor: float | None = None,
    predicted: bool = False,
    latency_compensation_ms: float | None = None,
    reid_confidence_level: str | None = None,
    identity_reason_code: str | None = None,
    identity_score: float | None = None,
    identity_sub_scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    message = {
        "type": "tracking",
        "version": "1.0",
        "source_version": SOURCE_VERSION,
        "sequence": sequence,
        "target_locked": bool(target_locked),
        "target_id": target_id,
        "error_x": max(-1.0, min(1.0, float(error_x))),
        "error_y": max(-1.0, min(1.0, float(error_y))),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "timestamp_ms": int(time() * 1000),
    }
    if frame_width is not None and frame_height is not None:
        message.update({
            "frame_width": int(frame_width),
            "frame_height": int(frame_height),
            "target_x": max(0.0, min(1.0, float(target_x or 0.0))),
            "target_y": max(0.0, min(1.0, float(target_y or 0.0))),
            "bbox_width": max(0.0, min(1.0, float(bbox_width or 0.0))),
            "bbox_height": max(0.0, min(1.0, float(bbox_height or 0.0))),
        })
    if zoom_factor is not None:
        message["zoom_factor"] = max(0.1, min(10.0, float(zoom_factor)))
    if predicted:
        message["predicted_target"] = True
    if latency_compensation_ms is not None:
        message["latency_compensation_ms"] = round(max(0.0, float(latency_compensation_ms)), 2)
    if reid_confidence_level:
        message["reid_confidence_level"] = str(reid_confidence_level)
    if identity_reason_code:
        message["identity_reason_code"] = str(identity_reason_code)
        message["identity_score"] = float(identity_score or 0.0)
        message["identity_sub_scores"] = {
            str(name): float(value) for name, value in (identity_sub_scores or {}).items()
        }
    return message


def parse_motor_status(payload: dict[str, Any] | str) -> MotorStatus | None:
    if isinstance(payload, str):
        decoded = decode_message(payload)
        if decoded is None:
            return None
        payload = decoded
    if payload.get("type") != "motor_status":
        return None
    return MotorStatus(
        docked=bool(payload.get("docked", False)),
        manual_ready=bool(payload.get("manual_ready", False)),
        system_tracking_enabled=payload.get("system_tracking_enabled"),
        last_error=str(payload["last_error"]) if payload.get("last_error") else None,
        timestamp_ms=int(payload.get("timestamp_ms", 0)),
        current_velocity=_dict_or_none(payload.get("current_velocity")),
        last_command=_dict_or_none(payload.get("last_command")),
        last_stop_reason=str(payload["last_stop_reason"]) if payload.get("last_stop_reason") else None,
        camera_zoom_factor=_float_or_none(payload.get("camera_zoom_factor")),
        camera_display_zoom_factor=_float_or_none(payload.get("camera_display_zoom_factor")),
        camera_frames_sent=max(0, int(payload.get("camera_frames_sent", 0))),
        camera_frames_dropped=max(0, int(payload.get("camera_frames_dropped", 0))),
    )


def unpack_camera_frame(data: bytes) -> tuple[bytes, int | None, int | None] | None:
    capture_timestamp_ms = None
    source_frame_id = None
    if data.startswith(CAMERA_FRAME_ENVELOPE_V2_MAGIC):
        if len(data) < CAMERA_FRAME_ENVELOPE_V2_HEADER_BYTES + 4:
            return None
        capture_timestamp_ms = int.from_bytes(
            data[len(CAMERA_FRAME_ENVELOPE_V2_MAGIC):len(CAMERA_FRAME_ENVELOPE_V2_MAGIC) + 8],
            byteorder="big",
            signed=False,
        )
        source_frame_id = int.from_bytes(
            data[len(CAMERA_FRAME_ENVELOPE_V2_MAGIC) + 8:CAMERA_FRAME_ENVELOPE_V2_HEADER_BYTES],
            byteorder="big",
            signed=False,
        )
        data = data[CAMERA_FRAME_ENVELOPE_V2_HEADER_BYTES:]
    elif data.startswith(CAMERA_FRAME_ENVELOPE_MAGIC):
        if len(data) < CAMERA_FRAME_ENVELOPE_HEADER_BYTES + 4:
            return None
        capture_timestamp_ms = int.from_bytes(
            data[len(CAMERA_FRAME_ENVELOPE_MAGIC):CAMERA_FRAME_ENVELOPE_HEADER_BYTES],
            byteorder="big",
            signed=False,
        )
        data = data[CAMERA_FRAME_ENVELOPE_HEADER_BYTES:]
    if len(data) < 4 or len(data) > 2_000_000 or not data.startswith(b"\xff\xd8"):
        return None
    return data, capture_timestamp_ms, source_frame_id


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
