"""Pure policy for converting CV frame state into outbound control commands."""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, time
from typing import Any

from autocamtracker.core.timestamps import (
    FrameTimeline,
    LatencyCompensator,
    TimestampMark,
    evaluate_latency_compensation,
)
from autocamtracker.server.camera_control_policy import (
    CameraControlDecision,
    CameraControlPolicy,
    CameraControlRequest,
)
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
    camera_control: CameraControlDecision | None = None


class ControlPolicy:
    """Own control policy state without mutating supplied CV domain objects."""

    def __init__(
        self,
        *,
        last_locked_zoom_factor: float = CENTER_ZOOM_FACTOR,
        last_unlocked_at: float | None = None,
        latency_compensator: LatencyCompensator | None = None,
        camera_control_policy: CameraControlPolicy | None = None,
    ) -> None:
        self.last_locked_zoom_factor = last_locked_zoom_factor
        self.last_unlocked_at = last_unlocked_at
        self.latency_compensator = latency_compensator
        self.camera_control_policy = camera_control_policy

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
        current_time = monotonic() if now is None else now
        source_fps = float(getattr(frame_data, "source_fps", None) or 30.0)
        latency_ms, frames_ahead, timing_fields = self._timing_fields(
            frame_data, source_fps, current_time
        )
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
            or (
                not getattr(frame_data, "motor_safe_to_track", True)
                and self.camera_control_policy is None
            )
        ):
            camera_control = None
            if self.camera_control_policy is not None:
                camera_control = self.camera_control_policy.evaluate(
                    CameraControlRequest(
                        target_locked=False,
                        zoom_target=self.last_locked_zoom_factor,
                    ),
                    now=current_time,
                )
                zoom_factor = camera_control.zoom_output
            else:
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
            payload = tracking_message(
                target_locked=False,
                sequence=sequence,
                zoom_factor=zoom_factor,
                latency_compensation_ms=latency_ms,
            )
            payload.update(timing_fields)
            if camera_control is not None:
                payload["camera_control"] = camera_control.to_dict()
            return FrameControlDecision(payload, camera_control=camera_control)

        status = frame_data.framing_status
        bbox = fresh_target.bbox
        target_id = frame_data.selected_global_vehicle_id
        if target_id is None:
            target_id = frame_data.selected_local_track_id
        zoom_factor = max(
            0.1,
            float(
                getattr(
                    status,
                    "zoom_target",
                    self.zoom_factor_for_framing(framing_mode),
                )
            ),
        )
        requested_zoom_factor = zoom_factor
        velocity_x, velocity_y = getattr(frame_data, "target_velocity", (0.0, 0.0))
        projected_x = max(0.0, min(float(frame_w), fresh_target.center[0] + float(velocity_x) * frames_ahead))
        projected_y = max(0.0, min(float(frame_h), fresh_target.center[1] + float(velocity_y) * frames_ahead))
        raw_error_x = (status.error_x + projected_x - fresh_target.center[0]) / max(1.0, frame_w / 2.0)
        raw_error_y = (status.error_y + projected_y - fresh_target.center[1]) / max(1.0, frame_h / 2.0)
        camera_control = None
        target_locked = True
        if self.camera_control_policy is not None:
            identity_decision = getattr(frame_data, "identity_decision", None)
            uncertainty_score = float(
                getattr(identity_decision, "score", fresh_target.confidence)
            )
            confidence_level = str(
                getattr(frame_data, "reid_confidence_level", "unknown")
            ).lower()
            uncertain = (
                not getattr(frame_data, "motor_safe_to_track", True)
                or confidence_level in {"low", "candidate", "lost", "searching"}
                or (
                    identity_decision is not None
                    and not bool(getattr(identity_decision, "accepted", False))
                )
            )
            camera_control = self.camera_control_policy.evaluate(
                CameraControlRequest(
                    target_locked=True,
                    error_x=raw_error_x,
                    error_y=raw_error_y,
                    zoom_target=requested_zoom_factor,
                    uncertain=uncertain,
                    uncertainty_score=max(0.0, min(1.0, uncertainty_score)),
                    predicted_target=fresh_target.status == "coasting",
                ),
                now=current_time,
            )
            raw_error_x = camera_control.error_x
            raw_error_y = camera_control.error_y
            zoom_factor = camera_control.zoom_output
            target_locked = not camera_control.frozen
        self.last_locked_zoom_factor = zoom_factor
        self.last_unlocked_at = None
        payload = tracking_message(
            target_locked=target_locked,
            target_id=target_id,
            error_x=raw_error_x,
            error_y=raw_error_y,
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
        payload.update(timing_fields)
        if camera_control is not None:
            payload["camera_control"] = camera_control.to_dict()
        payload.update({
            "framing_anchor": getattr(status, "framing_anchor", (0.5, 0.5)),
            "lead_room": getattr(status, "lead_room", (0.0, 0.0)),
            "desired_subject_scale": float(
                getattr(status, "desired_subject_scale", 0.0)
            ),
            "actual_subject_scale": float(
                getattr(status, "actual_subject_scale", 0.0)
            ),
            "zoom_target": requested_zoom_factor,
            "framing_reason_code": getattr(
                getattr(status, "reason_code", None), "value", None
            ),
        })
        return FrameControlDecision(
            payload,
            (projected_x, projected_y),
            camera_control,
        )

    def _timing_fields(
        self,
        frame_data: Any,
        source_fps: float,
        now_monotonic_s: float,
    ) -> tuple[float, float, dict[str, Any]]:
        timeline = getattr(frame_data, "timestamps", None)
        if not isinstance(timeline, FrameTimeline):
            latency_ms = max(
                0.0, float(getattr(frame_data, "latency_compensation_ms", 0.0) or 0.0)
            )
            frame_duration_ms = 1000.0 / max(1.0, source_fps)
            return latency_ms, min(3.0, latency_ms / frame_duration_ms), {}
        evaluated_at = TimestampMark(time() * 1000.0, now_monotonic_s * 1000.0)
        if self.latency_compensator is not None:
            breakdown, compensation = self.latency_compensator.evaluate(
                timeline,
                source_fps,
                evaluated_at=evaluated_at,
            )
        else:
            breakdown, compensation = evaluate_latency_compensation(
                timeline,
                source_fps,
                evaluated_at=evaluated_at,
            )
        return (
            compensation.applied_latency_ms,
            compensation.frames_ahead,
            {
                "frame_timestamps": timeline.to_dict(),
                "latency_breakdown": breakdown.to_dict(),
                "latency_compensation": compensation.to_dict(),
                "capture_timestamp_ms": timeline.capture_timestamp_ms,
            },
        )
