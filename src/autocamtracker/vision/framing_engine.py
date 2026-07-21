"""Composition decisions for subject anchor, lead room, scale, and zoom."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import hypot, isfinite
from typing import Any, Literal, Mapping


FramingMode = Literal["wide", "medium", "close"]


class FramingReasonCode(str, Enum):
    NO_SUBJECT = "NO_SUBJECT"
    STATIC_ANCHOR = "STATIC_ANCHOR"
    VELOCITY_LEAD = "VELOCITY_LEAD"
    BOUNDARY_CLAMPED = "BOUNDARY_CLAMPED"


@dataclass(frozen=True, slots=True)
class FramingProfile:
    desired_subject_scale: float
    anchor: tuple[float, float] = (0.5, 0.5)

    def __post_init__(self) -> None:
        if not 0.0 < self.desired_subject_scale <= 1.0:
            raise ValueError("desired_subject_scale must be in (0, 1]")
        if len(self.anchor) != 2 or not all(
            isfinite(value) and 0.0 <= value <= 1.0 for value in self.anchor
        ):
            raise ValueError("framing anchor must contain two normalized values")


DEFAULT_FRAMING_PROFILES: Mapping[FramingMode, FramingProfile] = {
    "wide": FramingProfile(0.30),
    "medium": FramingProfile(0.48),
    "close": FramingProfile(0.68),
}


@dataclass(frozen=True, slots=True)
class FramingEngineConfig:
    horizontal_lead_gain: float = 6.0
    vertical_lead_gain: float = 3.0
    max_horizontal_lead: float = 0.18
    max_vertical_lead: float = 0.10
    velocity_deadband_ratio: float = 0.002
    center_smoothing: float = 0.18
    zoom_smoothing: float = 0.22
    movement_dead_zone_ratio: float = 0.08
    min_zoom: float = 1.0
    max_zoom: float = 8.0
    max_subject_height_scale: float = 0.85

    def __post_init__(self) -> None:
        values = (
            self.horizontal_lead_gain,
            self.vertical_lead_gain,
            self.max_horizontal_lead,
            self.max_vertical_lead,
            self.velocity_deadband_ratio,
            self.center_smoothing,
            self.zoom_smoothing,
            self.movement_dead_zone_ratio,
            self.min_zoom,
            self.max_zoom,
            self.max_subject_height_scale,
        )
        if not all(isfinite(value) and value >= 0.0 for value in values):
            raise ValueError("framing engine values must be finite and non-negative")
        if not 0.0 <= self.center_smoothing <= 1.0:
            raise ValueError("center_smoothing must be in [0, 1]")
        if not 0.0 <= self.zoom_smoothing <= 1.0:
            raise ValueError("zoom_smoothing must be in [0, 1]")
        if not 0.0 <= self.movement_dead_zone_ratio <= 1.0:
            raise ValueError("movement_dead_zone_ratio must be in [0, 1]")
        if self.max_horizontal_lead > 0.45 or self.max_vertical_lead > 0.45:
            raise ValueError("framing lead limits cannot exceed 0.45")
        if self.min_zoom <= 0.0 or self.max_zoom < self.min_zoom:
            raise ValueError("framing zoom limits are invalid")
        if not 0.0 < self.max_subject_height_scale <= 1.0:
            raise ValueError("max_subject_height_scale must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class FramingDecision:
    crop_window: tuple[int, int, int, int]
    framing_mode: FramingMode
    subject_bbox: tuple[float, float, float, float] | None
    subject_center: tuple[float, float] | None
    framing_anchor: tuple[float, float]
    realized_anchor: tuple[float, float] | None
    lead_room: tuple[float, float]
    velocity: tuple[float, float]
    desired_subject_scale: float
    actual_subject_scale: float
    zoom_target: float
    raw_zoom_target: float
    boundary_clamped: bool
    reason_code: FramingReasonCode

    def to_dict(self) -> dict[str, Any]:
        return {
            "crop_window": self.crop_window,
            "framing_mode": self.framing_mode,
            "subject_bbox": self.subject_bbox,
            "subject_center": self.subject_center,
            "framing_anchor": self.framing_anchor,
            "realized_anchor": self.realized_anchor,
            "lead_room": self.lead_room,
            "velocity": self.velocity,
            "desired_subject_scale": self.desired_subject_scale,
            "actual_subject_scale": self.actual_subject_scale,
            "zoom_target": self.zoom_target,
            "raw_zoom_target": self.raw_zoom_target,
            "boundary_clamped": self.boundary_clamped,
            "reason_code": self.reason_code.value,
        }


class FramingEngine:
    """Stateful, renderer-independent framing planner."""

    def __init__(
        self,
        config: FramingEngineConfig | None = None,
        profiles: Mapping[FramingMode, FramingProfile] | None = None,
    ) -> None:
        self.config = config or FramingEngineConfig()
        self.profiles = dict(profiles or DEFAULT_FRAMING_PROFILES)
        if set(self.profiles) != {"wide", "medium", "close"}:
            raise ValueError("framing profiles must define wide, medium, and close")
        self._current_center: tuple[float, float] | None = None
        self._current_zoom: float | None = None

    def reset(self) -> None:
        self._current_center = None
        self._current_zoom = None

    def plan(
        self,
        *,
        frame_size: tuple[int, int],
        subject_bboxes: list[tuple[float, float, float, float]] | tuple[
            tuple[float, float, float, float], ...
        ],
        velocity: tuple[float, float] = (0.0, 0.0),
        framing_mode: FramingMode = "medium",
        output_aspect_ratio: float = 16.0 / 9.0,
    ) -> FramingDecision:
        frame_w, frame_h = frame_size
        if (
            frame_w <= 0
            or frame_h <= 0
            or not isfinite(output_aspect_ratio)
            or output_aspect_ratio <= 0.0
        ):
            raise ValueError("framing dimensions and aspect ratio must be positive")
        if framing_mode not in self.profiles:
            raise ValueError(f"unsupported framing mode: {framing_mode}")
        if len(velocity) != 2 or not all(isfinite(value) for value in velocity):
            raise ValueError("framing velocity must contain two finite values")
        profile = self.profiles[framing_mode]
        base_w, base_h = _base_crop_size(frame_w, frame_h, output_aspect_ratio)
        if not subject_bboxes:
            return FramingDecision(
                crop_window=(0, 0, frame_w, frame_h),
                framing_mode=framing_mode,
                subject_bbox=None,
                subject_center=None,
                framing_anchor=profile.anchor,
                realized_anchor=None,
                lead_room=(0.0, 0.0),
                velocity=velocity,
                desired_subject_scale=profile.desired_subject_scale,
                actual_subject_scale=0.0,
                zoom_target=1.0,
                raw_zoom_target=1.0,
                boundary_clamped=False,
                reason_code=FramingReasonCode.NO_SUBJECT,
            )

        for bbox in subject_bboxes:
            if (
                len(bbox) != 4
                or not all(isfinite(value) for value in bbox)
                or bbox[2] <= bbox[0]
                or bbox[3] <= bbox[1]
            ):
                raise ValueError("subject bboxes must contain finite positive-area edges")

        subject_bbox = _union_bbox(subject_bboxes)
        subject_center = _bbox_center(subject_bbox)
        subject_w = max(1.0, subject_bbox[2] - subject_bbox[0])
        subject_h = max(1.0, subject_bbox[3] - subject_bbox[1])
        width_zoom = profile.desired_subject_scale * base_w / subject_w
        height_safe_zoom = self.config.max_subject_height_scale * base_h / subject_h
        raw_zoom = _clamp(
            min(width_zoom, height_safe_zoom),
            self.config.min_zoom,
            self.config.max_zoom,
        )
        zoom = self._smooth_zoom(raw_zoom)
        crop_w = max(1.0, min(base_w, base_w / zoom))
        crop_h = max(1.0, min(base_h, base_h / zoom))

        anchor, lead_room, moving = self._velocity_anchor(
            profile.anchor, velocity, frame_w, frame_h
        )
        desired_center = (
            subject_center[0] + (0.5 - anchor[0]) * crop_w,
            subject_center[1] + (0.5 - anchor[1]) * crop_h,
        )
        smooth_center = self._smooth_center(desired_center, crop_w, crop_h)
        crop_window, boundary_clamped = _crop_window(
            smooth_center, crop_w, crop_h, frame_w, frame_h
        )
        x, y, width, height = crop_window
        realized_anchor = (
            _clamp((subject_center[0] - x) / max(1.0, width), 0.0, 1.0),
            _clamp((subject_center[1] - y) / max(1.0, height), 0.0, 1.0),
        )
        actual_scale = subject_w / max(1.0, float(width))
        if boundary_clamped:
            reason = FramingReasonCode.BOUNDARY_CLAMPED
        elif moving:
            reason = FramingReasonCode.VELOCITY_LEAD
        else:
            reason = FramingReasonCode.STATIC_ANCHOR
        return FramingDecision(
            crop_window=crop_window,
            framing_mode=framing_mode,
            subject_bbox=subject_bbox,
            subject_center=subject_center,
            framing_anchor=anchor,
            realized_anchor=realized_anchor,
            lead_room=lead_room,
            velocity=velocity,
            desired_subject_scale=profile.desired_subject_scale,
            actual_subject_scale=actual_scale,
            zoom_target=zoom,
            raw_zoom_target=raw_zoom,
            boundary_clamped=boundary_clamped,
            reason_code=reason,
        )

    def _velocity_anchor(
        self,
        base_anchor: tuple[float, float],
        velocity: tuple[float, float],
        frame_w: int,
        frame_h: int,
    ) -> tuple[tuple[float, float], tuple[float, float], bool]:
        normalized_x = velocity[0] / max(1.0, float(frame_w))
        normalized_y = velocity[1] / max(1.0, float(frame_h))
        speed_ratio = hypot(normalized_x, normalized_y)
        if speed_ratio <= self.config.velocity_deadband_ratio:
            return base_anchor, (0.0, 0.0), False
        lead_x = _clamp(
            normalized_x * self.config.horizontal_lead_gain,
            -self.config.max_horizontal_lead,
            self.config.max_horizontal_lead,
        )
        lead_y = _clamp(
            normalized_y * self.config.vertical_lead_gain,
            -self.config.max_vertical_lead,
            self.config.max_vertical_lead,
        )
        anchor = (
            _clamp(base_anchor[0] - lead_x, 0.05, 0.95),
            _clamp(base_anchor[1] - lead_y, 0.05, 0.95),
        )
        return anchor, (lead_x, lead_y), True

    def _smooth_zoom(self, desired_zoom: float) -> float:
        if self._current_zoom is None:
            self._current_zoom = desired_zoom
            return desired_zoom
        alpha = self.config.zoom_smoothing
        self._current_zoom += (desired_zoom - self._current_zoom) * alpha
        return self._current_zoom

    def _smooth_center(
        self,
        desired_center: tuple[float, float],
        crop_w: float,
        crop_h: float,
    ) -> tuple[float, float]:
        if self._current_center is None:
            self._current_center = desired_center
            return desired_center
        delta_x = desired_center[0] - self._current_center[0]
        delta_y = desired_center[1] - self._current_center[1]
        if (
            abs(delta_x) <= crop_w * self.config.movement_dead_zone_ratio
            and abs(delta_y) <= crop_h * self.config.movement_dead_zone_ratio
        ):
            return self._current_center
        alpha = self.config.center_smoothing
        self._current_center = (
            self._current_center[0] + delta_x * alpha,
            self._current_center[1] + delta_y * alpha,
        )
        return self._current_center


def _base_crop_size(
    frame_w: int, frame_h: int, aspect_ratio: float
) -> tuple[float, float]:
    width = float(frame_w)
    height = width / aspect_ratio
    if height > frame_h:
        height = float(frame_h)
        width = height * aspect_ratio
    return width, height


def _crop_window(
    center: tuple[float, float],
    crop_w: float,
    crop_h: float,
    frame_w: int,
    frame_h: int,
) -> tuple[tuple[int, int, int, int], bool]:
    width = max(1, min(frame_w, int(round(crop_w))))
    height = max(1, min(frame_h, int(round(crop_h))))
    ideal_x = int(round(center[0] - width / 2.0))
    ideal_y = int(round(center[1] - height / 2.0))
    x = max(0, min(frame_w - width, ideal_x))
    y = max(0, min(frame_h - height, ideal_y))
    return (x, y, width, height), (x != ideal_x or y != ideal_y)


def _union_bbox(
    bboxes: list[tuple[float, float, float, float]] | tuple[
        tuple[float, float, float, float], ...
    ],
) -> tuple[float, float, float, float]:
    return (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )


def _bbox_center(
    bbox: tuple[float, float, float, float]
) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
