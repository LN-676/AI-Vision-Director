"""Sequencing and rate limiting for outbound control messages."""

from __future__ import annotations

from time import monotonic, time
from typing import Any, Callable

from autocamtracker.server.control_policy import CENTER_ZOOM_FACTOR, ControlPolicy, FrameControlDecision
from autocamtracker.server.protocol import tracking_message


class ControlPublisher:
    def __init__(
        self,
        send: Callable[[dict[str, Any]], None],
        *,
        publish_hz: float = 20.0,
        policy: ControlPolicy | None = None,
    ) -> None:
        self.send = send
        self.publish_hz = publish_hz
        self.policy = policy or ControlPolicy()
        self.sequence = 0
        self._last_publish_at = 0.0

    def publish_frame(self, frame_data: Any, frame_shape: Any) -> FrameControlDecision | None:
        interval = 1.0 / max(1.0, self.publish_hz)
        now = monotonic()
        if now - self._last_publish_at < interval:
            return None
        self._last_publish_at = now
        self.sequence += 1
        decision = self.policy.frame_command(frame_data, frame_shape, self.sequence, now=now)
        payload = dict(decision.payload)
        if getattr(frame_data, "receive_latency_ms", None) is not None:
            payload["receive_latency_ms"] = round(float(frame_data.receive_latency_ms), 2)
        if getattr(frame_data, "decode_time_ms", 0.0):
            payload["decode_time_ms"] = round(float(frame_data.decode_time_ms), 2)
        self.send(payload)
        return FrameControlDecision(
            payload,
            decision.projected_target_center,
            decision.camera_control,
        )

    def publish_test_pulse(self, error_x: float = 0.12) -> None:
        self.sequence += 1
        self.send(tracking_message(
            target_locked=True,
            target_id=999,
            error_x=error_x,
            confidence=1.0,
            sequence=self.sequence,
        ))

    def publish_stop(self, zoom_factor: float | None = CENTER_ZOOM_FACTOR) -> None:
        self.sequence += 1
        self.send(tracking_message(
            target_locked=False,
            sequence=self.sequence,
            zoom_factor=zoom_factor,
        ))

    def publish_control(self, action: str) -> None:
        self.send({"type": "control", "action": action, "timestamp_ms": int(time() * 1000)})
