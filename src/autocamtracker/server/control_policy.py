"""Pure policy for converting CV frame state into outbound control commands."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from autocamtracker.server.protocol import tracking_message


FRAMING_ZOOM_FACTORS = {"wide": 1.0, "medium": 1.6, "close": 2.4}
CENTER_ZOOM_FACTOR = FRAMING_ZOOM_FACTORS["wide"]
LOST_ZOOM_HOLD_SECONDS = 1.0
LOST_ZOOM_RAMP_SECONDS = 2.0
COASTING_COMMAND_FRAMES = 12


@dataclass(frozen=True)
class FrameControlDecision:
    payload: dict[str, Any]
    projected_target_center: tuple[float, float] | None = None


class ControlPolicy:
    """Own control policy state without mutating supplied CV domain objects."""

    def __init__(
        self,
        *,
        last_locked_zoom_factor: float = CENTER_ZOOM_FACTOR,
        last_unlocked_at: float | None = None,
    ) -> None:
        self.last_locked_zoom_factor = last_locked_zoom_factor
        self.last_unlocked_at = last_unlocked_at

    @staticmethod
    def zoom_factor_for_framing(framing_mode: str | None) -> float:
        return FRAMING_ZOOM_FACTORS.get(framing_mode or "medium", FRAMING_ZOOM_FACTORS["medium"])

    @staticmethod
    def accept_remote_control(payload: dict[str, Any]) -> dict[str, Any] | None:
        if payload.get("type") != "control":
            return None
        action = str(payload.get("action") or "").strip()
        if not action:
            return None
        normalized = dict(payload)
        normalized["action"] = action
        return normalized

    def frame_command(
        self,
        frame_data: Any,
        frame_shape: Any,
        sequence: int = 0,
        *,
        now: float | None = None,
    ) -> FrameControlDecision:
        frame_h, frame_w = frame_shape[:2]
        fresh_target = next(
            (
                target
                for target in frame_data.selected_targets
                if (
                    (target.status == "tracking" and target.lost_frame_count == 0)
                    or (target.status == "coasting" and target.lost_frame_count <= COASTING_COMMAND_FRAMES)
                )
            ),
            None,
        )
        framing_mode = getattr(getattr(frame_data, "framing_status", None), "framing_mode", "medium")
        if (
            fresh_target is None
            or frame_data.tracking_status != "tracking"
            or not getattr(frame_data, "motor_safe_to_track", True)
        ):
            current_time = monotonic() if now is None else now
            if self.last_unlocked_at is None:
                self.last_unlocked_at = current_time
            elapsed = current_time - self.last_unlocked_at
            if elapsed <= LOST_ZOOM_HOLD_SECONDS:
                zoom_factor = self.last_locked_zoom_factor
            else:
                ramp = min(1.0, (elapsed - LOST_ZOOM_HOLD_SECONDS) / LOST_ZOOM_RAMP_SECONDS)
                zoom_factor = self.last_locked_zoom_factor + (
                    CENTER_ZOOM_FACTOR - self.last_locked_zoom_factor
                ) * ramp
            return FrameControlDecision(
                tracking_message(target_locked=False, sequence=sequence, zoom_factor=zoom_factor)
            )

        status = frame_data.framing_status
        bbox = fresh_target.bbox
        target_id = frame_data.selected_global_vehicle_id
        if target_id is None:
            target_id = frame_data.selected_local_track_id
        zoom_factor = self.zoom_factor_for_framing(framing_mode)
        self.last_locked_zoom_factor = zoom_factor
        self.last_unlocked_at = None
        latency_ms = float(getattr(frame_data, "latency_compensation_ms", 0.0) or 0.0)
        source_fps = float(getattr(frame_data, "source_fps", None) or 30.0)
        frames_ahead = min(3.0, max(0.0, latency_ms / max(1.0, 1000.0 / max(1.0, source_fps))))
        velocity_x, velocity_y = getattr(frame_data, "target_velocity", (0.0, 0.0))
        projected_x = max(0.0, min(float(frame_w), fresh_target.center[0] + float(velocity_x) * frames_ahead))
        projected_y = max(0.0, min(float(frame_h), fresh_target.center[1] + float(velocity_y) * frames_ahead))
        payload = tracking_message(
            target_locked=True,
            target_id=target_id,
            error_x=(status.error_x + projected_x - fresh_target.center[0]) / max(1.0, frame_w / 2.0),
            error_y=(status.error_y + projected_y - fresh_target.center[1]) / max(1.0, frame_h / 2.0),
            confidence=fresh_target.confidence,
            sequence=sequence,
            frame_width=frame_w,
            frame_height=frame_h,
            target_x=projected_x / max(1.0, frame_w),
            target_y=projected_y / max(1.0, frame_h),
            bbox_width=(bbox[2] - bbox[0]) / max(1.0, frame_w),
            bbox_height=(bbox[3] - bbox[1]) / max(1.0, frame_h),
            zoom_factor=zoom_factor,
            predicted=fresh_target.status == "coasting",
            latency_compensation_ms=latency_ms,
            reid_confidence_level=getattr(frame_data, "reid_confidence_level", None),
            identity_reason_code=(
                frame_data.identity_decision.reason_code.value
                if getattr(frame_data, "identity_decision", None) is not None else None
            ),
            identity_score=(
                frame_data.identity_decision.score
                if getattr(frame_data, "identity_decision", None) is not None else None
            ),
            identity_sub_scores=(
                dict(frame_data.identity_decision.sub_scores)
                if getattr(frame_data, "identity_decision", None) is not None else None
            ),
        )
        return FrameControlDecision(payload, (projected_x, projected_y))
