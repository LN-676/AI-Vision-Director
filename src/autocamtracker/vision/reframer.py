"""OpenCV rendering adapter for renderer-independent framing decisions."""

from __future__ import annotations

from dataclasses import dataclass
from autocamtracker.tracking.target_tracker import SelectedTarget
from autocamtracker.vision.framing_engine import (
    FramingDecision,
    FramingEngine,
    FramingMode,
    FramingReasonCode,
)


@dataclass
class FramingConfig:
    output_width: int = 640
    output_height: int = 360
    framing_mode: FramingMode = "medium"
    smooth_factor: float = 0.18
    dead_zone_ratio: float = 0.08
    fallback_to_original: bool = True


@dataclass
class FramingStatus:
    crop_window: tuple[int, int, int, int]
    framing_mode: FramingMode
    target_center: tuple[float, float] | None
    frame_center: tuple[float, float]
    error_x: float
    error_y: float
    framing_anchor: tuple[float, float] = (0.5, 0.5)
    realized_anchor: tuple[float, float] | None = None
    lead_room: tuple[float, float] = (0.0, 0.0)
    desired_subject_scale: float = 0.0
    actual_subject_scale: float = 0.0
    zoom_target: float = 1.0
    raw_zoom_target: float = 1.0
    boundary_clamped: bool = False
    reason_code: FramingReasonCode = FramingReasonCode.NO_SUBJECT

    def to_dict(self) -> dict[str, object]:
        return {
            "crop_window": self.crop_window,
            "framing_mode": self.framing_mode,
            "target_center": self.target_center,
            "frame_center": self.frame_center,
            "error_x": self.error_x,
            "error_y": self.error_y,
            "framing_anchor": self.framing_anchor,
            "realized_anchor": self.realized_anchor,
            "lead_room": self.lead_room,
            "desired_subject_scale": self.desired_subject_scale,
            "actual_subject_scale": self.actual_subject_scale,
            "zoom_target": self.zoom_target,
            "raw_zoom_target": self.raw_zoom_target,
            "boundary_clamped": self.boundary_clamped,
            "reason_code": self.reason_code.value,
        }


class Reframer:
    """Creates the after-view pixels from a FramingEngine plan."""

    def __init__(
        self,
        config: FramingConfig | None = None,
        *,
        engine: FramingEngine,
    ) -> None:
        self.config = config or FramingConfig()
        self.engine = engine

    def set_framing_mode(self, mode: FramingMode) -> None:
        self.config.framing_mode = mode

    def render(
        self,
        frame,
        selected_targets: list[SelectedTarget],
        velocity: tuple[float, float] = (0.0, 0.0),
    ):
        import cv2

        status = self.status(frame, selected_targets, velocity)
        x, y, width, height = status.crop_window
        if not selected_targets:
            output = cv2.resize(frame, (self.config.output_width, self.config.output_height))
            return output, status

        cropped = frame[y : y + height, x : x + width]
        output = cv2.resize(cropped, (self.config.output_width, self.config.output_height))
        return output, status

    def status(
        self,
        frame,
        selected_targets: list[SelectedTarget],
        velocity: tuple[float, float] = (0.0, 0.0),
    ) -> FramingStatus:
        frame_h, frame_w = frame.shape[:2]
        decision = self.engine.plan(
            frame_size=(frame_w, frame_h),
            subject_bboxes=[target.bbox for target in selected_targets],
            velocity=velocity,
            framing_mode=self.config.framing_mode,
            output_aspect_ratio=(
                self.config.output_width / max(1.0, float(self.config.output_height))
            ),
        )
        target_center = decision.subject_center
        frame_center = (frame_w / 2.0, frame_h / 2.0)
        anchor_point = (
            decision.framing_anchor[0] * frame_w,
            decision.framing_anchor[1] * frame_h,
        )
        return self._status_from_decision(
            decision,
            frame_center,
            error=(
                target_center[0] - anchor_point[0] if target_center is not None else 0.0,
                target_center[1] - anchor_point[1] if target_center is not None else 0.0,
            ),
        )

    @staticmethod
    def _status_from_decision(
        decision: FramingDecision,
        frame_center: tuple[float, float],
        error: tuple[float, float],
    ) -> FramingStatus:
        return FramingStatus(
            crop_window=decision.crop_window,
            framing_mode=decision.framing_mode,
            target_center=decision.subject_center,
            frame_center=frame_center,
            error_x=error[0],
            error_y=error[1],
            framing_anchor=decision.framing_anchor,
            realized_anchor=decision.realized_anchor,
            lead_room=decision.lead_room,
            desired_subject_scale=decision.desired_subject_scale,
            actual_subject_scale=decision.actual_subject_scale,
            zoom_target=decision.zoom_target,
            raw_zoom_target=decision.raw_zoom_target,
            boundary_clamped=decision.boundary_clamped,
            reason_code=decision.reason_code,
        )

    def make_comparison_frame(self, before_frame, after_frame):
        import cv2
        import numpy as np

        before = cv2.resize(before_frame, (self.config.output_width, self.config.output_height))
        after = cv2.resize(after_frame, (self.config.output_width, self.config.output_height))
        return np.hstack([before, after])

    def reset(self) -> None:
        self.engine.reset()
