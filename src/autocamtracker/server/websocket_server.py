"""Compatibility façade composing the Phase 8 WebSocket components."""

from __future__ import annotations

from threading import Lock
from time import monotonic
from typing import Any, Callable

from autocamtracker.core.telemetry_logger import TelemetryLogger
from autocamtracker.core.timestamps import LatencyCompensator
from autocamtracker.server.camera_control_policy import CameraControlPolicy
from autocamtracker.server.camera_control_policy import CameraControlDecision
from autocamtracker.server.camera_stream_receiver import CameraStreamReceiver
from autocamtracker.server.control_policy import (
    CENTER_ZOOM_FACTOR,
    COASTING_COMMAND_FRAMES,
    FRAMING_ZOOM_FACTORS,
    LOST_ZOOM_HOLD_SECONDS,
    LOST_ZOOM_RAMP_SECONDS,
    ControlPolicy,
)
from autocamtracker.server.control_publisher import ControlPublisher
from autocamtracker.server.protocol import (
    CAMERA_FRAME_ENVELOPE_HEADER_BYTES,
    CAMERA_FRAME_ENVELOPE_MAGIC,
    SOURCE_VERSION,
    MotorStatus,
    decode_message,
    encode_message,
    parse_motor_status,
    tracking_message,
)
from autocamtracker.server.transport import TrackingServerConfig, WebSocketTransport


# Compatibility state for callers of the legacy module-level policy function.
_last_locked_zoom_factor = CENTER_ZOOM_FACTOR
_last_unlocked_at: float | None = None


def zoom_factor_for_framing(framing_mode: str | None) -> float:
    return ControlPolicy.zoom_factor_for_framing(framing_mode)


def frame_tracking_message(frame_data: Any, frame_shape: Any, sequence: int = 0) -> dict[str, Any]:
    """Compatibility adapter around the pure Phase 8 control policy."""

    global _last_locked_zoom_factor, _last_unlocked_at
    policy = ControlPolicy(
        last_locked_zoom_factor=_last_locked_zoom_factor,
        last_unlocked_at=_last_unlocked_at,
    )
    decision = policy.frame_command(frame_data, frame_shape, sequence, now=monotonic())
    _last_locked_zoom_factor = policy.last_locked_zoom_factor
    _last_unlocked_at = policy.last_unlocked_at
    if decision.projected_target_center is not None:
        frame_data.projected_target_center = decision.projected_target_center
    return decision.payload


class TrackingWebSocketServer:
    """Stable application-facing API over the split WebSocket stack."""

    def __init__(
        self,
        config: TrackingServerConfig | None = None,
        on_status: Callable[[str], None] | None = None,
        on_control: Callable[[dict[str, Any]], None] | None = None,
        telemetry_logger: TelemetryLogger | None = None,
        latency_compensator: LatencyCompensator | None = None,
        camera_control_policy: CameraControlPolicy | None = None,
    ) -> None:
        self.config = config or TrackingServerConfig()
        self.on_status = on_status
        self.on_control = on_control
        self.telemetry_logger = telemetry_logger
        self._motor_status_lock = Lock()
        self._latest_motor_status: MotorStatus | None = None
        self._latest_desktop_state: dict[str, Any] | None = None
        self._last_camera_control_decision: CameraControlDecision | None = None
        self.camera_stream_receiver = CameraStreamReceiver(
            on_status=self._notify,
            on_event=self._component_event,
        )
        self.control_policy = ControlPolicy(
            latency_compensator=latency_compensator,
            camera_control_policy=camera_control_policy,
        )
        self.transport = WebSocketTransport(
            self.config,
            on_binary=self._accept_camera_frame,
            on_text=self._accept_text_message,
            initial_messages=self._initial_messages,
            on_connected=self._client_connected,
            on_disconnected=self._client_disconnected,
            on_status=self._notify,
            on_event=self._component_event,
        )
        self.control_publisher = ControlPublisher(
            self.publish,
            publish_hz=self.config.publish_hz,
            policy=self.control_policy,
        )

    @property
    def is_running(self) -> bool:
        return self.transport.is_running

    @property
    def client_count(self) -> int:
        return self.transport.client_count

    @property
    def motor_status(self) -> MotorStatus | None:
        with self._motor_status_lock:
            return self._latest_motor_status

    @property
    def motor_ready(self) -> bool:
        status = self.motor_status
        return bool(status and status.ready)

    @property
    def last_camera_control_decision(self) -> CameraControlDecision | None:
        return self._last_camera_control_decision

    @property
    def local_urls(self) -> list[str]:
        return self.transport.local_urls

    @property
    def preferred_url(self) -> str:
        return self.transport.preferred_url

    @property
    def _sequence(self) -> int:
        return self.control_publisher.sequence

    @_sequence.setter
    def _sequence(self, value: int) -> None:
        self.control_publisher.sequence = value

    def start(self) -> None:
        self.transport.start()

    def stop(self) -> None:
        self.transport.stop()

    def publish_frame(self, frame_data: Any, frame_shape: Any) -> None:
        decision = self.control_publisher.publish_frame(frame_data, frame_shape)
        if decision is not None:
            self._last_camera_control_decision = decision.camera_control
            if decision.projected_target_center is not None:
                frame_data.projected_target_center = decision.projected_target_center

    def publish_test_pulse(self, error_x: float = 0.12) -> None:
        self.control_publisher.publish_test_pulse(error_x)

    def publish_stop(self, zoom_factor: float | None = CENTER_ZOOM_FACTOR) -> None:
        self.control_publisher.publish_stop(zoom_factor)

    def reset_camera_control(self) -> None:
        policy = self.control_policy.camera_control_policy
        if policy is not None:
            policy.reset()
        self._last_camera_control_decision = None

    def publish_control(self, action: str) -> None:
        self.control_publisher.publish_control(action)

    def read_latest_frame(self):
        return self.camera_stream_receiver.read_latest_frame()

    def latest_frame_timing(self) -> dict[str, Any]:
        return self.camera_stream_receiver.latest_frame_timing()

    def publish(self, payload: dict[str, Any]) -> None:
        if payload.get("type") == "desktop_state":
            self._latest_desktop_state = dict(payload)
        if payload.get("type") in {"tracking", "desktop_state"}:
            self._log("ws_send", payload=payload)
        self.transport.publish_text(encode_message(payload))

    def _initial_messages(self) -> list[str]:
        messages = [encode_message(tracking_message(target_locked=False, sequence=self._sequence))]
        if self._latest_desktop_state is not None:
            messages.append(encode_message(self._latest_desktop_state))
        return messages

    def _accept_camera_frame(self, data: bytes) -> None:
        self.camera_stream_receiver.accept(data)

    def _accept_text_message(self, message: str) -> None:
        payload = decode_message(message)
        if payload is None:
            return
        if payload.get("type") == "motor_status":
            self._accept_motor_status(payload)
        elif payload.get("type") == "control":
            self._accept_control(payload)

    def _accept_motor_status(self, payload: dict[str, Any] | str) -> None:
        status = parse_motor_status(payload)
        if status is None:
            return
        with self._motor_status_lock:
            self._latest_motor_status = status
        self._log("motor_status", status=status)
        state = "motor ready" if status.ready else "motor not ready"
        if status.last_error:
            state = f"motor error: {status.last_error}"
        self._notify(f"iPhone connected · {state}")

    def _accept_control(self, payload: dict[str, Any]) -> None:
        accepted = self.control_policy.accept_remote_control(payload)
        if accepted is None or self.on_control is None:
            return
        self._log("ws_control", payload=accepted)
        self.on_control(accepted)
        self._notify(f"iPhone control: {accepted['action']}")

    def _client_connected(self, count: int) -> None:
        self._notify(f"iPhone connected ({count})")

    def _client_disconnected(self, count: int) -> None:
        if count == 0:
            with self._motor_status_lock:
                self._latest_motor_status = None
        self._notify("iPhone disconnected" if count == 0 else f"iPhone connected ({count})")

    @staticmethod
    def _active_interface_addresses() -> list[tuple[str, str]]:
        return WebSocketTransport._active_interface_addresses()

    def _component_event(self, event: str, fields: dict[str, Any]) -> None:
        self._log(event, **fields)

    def _notify(self, message: str) -> None:
        if self.on_status is not None:
            self.on_status(message)

    def _log(self, event: str, **fields: Any) -> None:
        if self.telemetry_logger is not None:
            self.telemetry_logger.log(event, **fields)


__all__ = [
    "CAMERA_FRAME_ENVELOPE_HEADER_BYTES",
    "CAMERA_FRAME_ENVELOPE_MAGIC",
    "CENTER_ZOOM_FACTOR",
    "COASTING_COMMAND_FRAMES",
    "FRAMING_ZOOM_FACTORS",
    "LOST_ZOOM_HOLD_SECONDS",
    "LOST_ZOOM_RAMP_SECONDS",
    "MotorStatus",
    "SOURCE_VERSION",
    "TrackingServerConfig",
    "TrackingWebSocketServer",
    "frame_tracking_message",
    "tracking_message",
    "zoom_factor_for_framing",
]
