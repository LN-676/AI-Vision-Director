"""Stateful camera-command shaping and uncertainty safety policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any


class CameraControlReasonCode(str, Enum):
    TRACKING = "TRACKING"
    DEAD_ZONE = "DEAD_ZONE"
    HYSTERESIS_TRACKING = "HYSTERESIS_TRACKING"
    TARGET_LOST_ZOOM_HOLD = "TARGET_LOST_ZOOM_HOLD"
    TARGET_LOST_ZOOM_RETURN = "TARGET_LOST_ZOOM_RETURN"
    UNCERTAINTY_FREEZE = "UNCERTAINTY_FREEZE"


@dataclass(frozen=True, slots=True)
class CameraControlConfig:
    dead_zone_enter: float = 0.06
    dead_zone_exit: float = 0.035
    low_pass_alpha: float = 0.35
    yaw_gain: float = 1.0
    pitch_gain: float = 1.0
    max_yaw_velocity: float = 0.35
    max_pitch_velocity: float = 0.22
    max_yaw_acceleration: float = 1.20
    max_pitch_acceleration: float = 0.80
    zoom_ramp_per_second: float = 0.80
    zoom_hold_seconds: float = 1.0
    zoom_return_target: float = 1.0
    min_zoom: float = 1.0
    max_zoom: float = 8.0
    uncertainty_threshold: float = 0.65
    nominal_interval_seconds: float = 0.05
    max_interval_seconds: float = 0.25

    def __post_init__(self) -> None:
        values = (
            self.dead_zone_enter,
            self.dead_zone_exit,
            self.low_pass_alpha,
            self.yaw_gain,
            self.pitch_gain,
            self.max_yaw_velocity,
            self.max_pitch_velocity,
            self.max_yaw_acceleration,
            self.max_pitch_acceleration,
            self.zoom_ramp_per_second,
            self.zoom_hold_seconds,
            self.zoom_return_target,
            self.min_zoom,
            self.max_zoom,
            self.uncertainty_threshold,
            self.nominal_interval_seconds,
            self.max_interval_seconds,
        )
        if not all(isfinite(value) and value >= 0.0 for value in values):
            raise ValueError("camera control configuration must be finite and non-negative")
        if self.dead_zone_exit > self.dead_zone_enter:
            raise ValueError("dead_zone_exit cannot exceed dead_zone_enter")
        if not 0.0 < self.low_pass_alpha <= 1.0:
            raise ValueError("low_pass_alpha must be in (0, 1]")
        if self.max_yaw_velocity <= 0.0 or self.max_pitch_velocity <= 0.0:
            raise ValueError("camera velocity limits must be positive")
        if self.max_yaw_acceleration <= 0.0 or self.max_pitch_acceleration <= 0.0:
            raise ValueError("camera acceleration limits must be positive")
        if self.zoom_ramp_per_second <= 0.0:
            raise ValueError("zoom_ramp_per_second must be positive")
        if self.min_zoom <= 0.0 or self.max_zoom < self.min_zoom:
            raise ValueError("camera zoom limits are invalid")
        if not self.min_zoom <= self.zoom_return_target <= self.max_zoom:
            raise ValueError("zoom_return_target must be inside zoom limits")
        if not 0.0 <= self.uncertainty_threshold <= 1.0:
            raise ValueError("uncertainty_threshold must be in [0, 1]")
        if (
            self.nominal_interval_seconds <= 0.0
            or self.max_interval_seconds < self.nominal_interval_seconds
        ):
            raise ValueError("camera control intervals are invalid")


@dataclass(frozen=True, slots=True)
class CameraControlRequest:
    target_locked: bool
    error_x: float = 0.0
    error_y: float = 0.0
    zoom_target: float = 1.0
    uncertain: bool = False
    uncertainty_score: float = 1.0
    predicted_target: bool = False

    def __post_init__(self) -> None:
        values = (
            self.error_x,
            self.error_y,
            self.zoom_target,
            self.uncertainty_score,
        )
        if not all(isfinite(value) for value in values):
            raise ValueError("camera control request values must be finite")
        if self.zoom_target <= 0.0:
            raise ValueError("camera zoom target must be positive")
        if not 0.0 <= self.uncertainty_score <= 1.0:
            raise ValueError("uncertainty_score must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class CameraControlDecision:
    error_x: float
    error_y: float
    yaw_velocity: float
    pitch_velocity: float
    yaw_acceleration: float
    pitch_acceleration: float
    zoom_target: float
    zoom_output: float
    target_locked: bool
    frozen: bool
    x_axis_active: bool
    y_axis_active: bool
    uncertainty_score: float
    reason_code: CameraControlReasonCode

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_x": self.error_x,
            "error_y": self.error_y,
            "yaw_velocity": self.yaw_velocity,
            "pitch_velocity": self.pitch_velocity,
            "yaw_acceleration": self.yaw_acceleration,
            "pitch_acceleration": self.pitch_acceleration,
            "zoom_target": self.zoom_target,
            "zoom_output": self.zoom_output,
            "target_locked": self.target_locked,
            "frozen": self.frozen,
            "x_axis_active": self.x_axis_active,
            "y_axis_active": self.y_axis_active,
            "uncertainty_score": self.uncertainty_score,
            "reason_code": self.reason_code.value,
        }


class CameraControlPolicy:
    """Shapes raw framing errors into bounded, auditable camera commands."""

    def __init__(self, config: CameraControlConfig | None = None) -> None:
        self.config = config or CameraControlConfig()
        self._yaw_velocity = 0.0
        self._pitch_velocity = 0.0
        self._x_axis_active = False
        self._y_axis_active = False
        self._current_zoom = self.config.zoom_return_target
        self._last_update_at: float | None = None
        self._lost_started_at: float | None = None

    @property
    def current_zoom(self) -> float:
        return self._current_zoom

    def reset(self, *, zoom: float | None = None) -> None:
        self._yaw_velocity = 0.0
        self._pitch_velocity = 0.0
        self._x_axis_active = False
        self._y_axis_active = False
        self._current_zoom = _clamp(
            self.config.zoom_return_target if zoom is None else zoom,
            self.config.min_zoom,
            self.config.max_zoom,
        )
        self._last_update_at = None
        self._lost_started_at = None

    def evaluate(
        self,
        request: CameraControlRequest,
        *,
        now: float,
    ) -> CameraControlDecision:
        if not isfinite(now):
            raise ValueError("camera control time must be finite")
        delta_time = self._delta_time(now)
        zoom_target = _clamp(
            request.zoom_target, self.config.min_zoom, self.config.max_zoom
        )
        uncertainty_freeze = (
            request.uncertain
            or request.uncertainty_score < self.config.uncertainty_threshold
        )
        if uncertainty_freeze:
            return self._stopped_decision(
                request,
                zoom_target,
                CameraControlReasonCode.UNCERTAINTY_FREEZE,
                frozen=True,
            )
        if not request.target_locked:
            return self._lost_decision(request, zoom_target, now, delta_time)

        self._lost_started_at = None
        self._current_zoom = _move_towards(
            self._current_zoom,
            zoom_target,
            self.config.zoom_ramp_per_second * delta_time,
        )
        previous_yaw = self._yaw_velocity
        previous_pitch = self._pitch_velocity
        yaw, self._x_axis_active, x_hysteresis = self._axis_velocity(
            request.error_x,
            previous_yaw,
            self._x_axis_active,
            gain=self.config.yaw_gain,
            max_velocity=self.config.max_yaw_velocity,
            max_acceleration=self.config.max_yaw_acceleration,
            delta_time=delta_time,
        )
        # Tracking error_y is image-space down-positive; physical pitch is the
        # inverse sign, matching the iOS DockKit adapter.
        pitch, self._y_axis_active, y_hysteresis = self._axis_velocity(
            -request.error_y,
            previous_pitch,
            self._y_axis_active,
            gain=self.config.pitch_gain,
            max_velocity=self.config.max_pitch_velocity,
            max_acceleration=self.config.max_pitch_acceleration,
            delta_time=delta_time,
        )
        self._yaw_velocity = yaw
        self._pitch_velocity = pitch
        yaw_acceleration = (yaw - previous_yaw) / delta_time
        pitch_acceleration = (pitch - previous_pitch) / delta_time
        if not self._x_axis_active and not self._y_axis_active:
            reason = CameraControlReasonCode.DEAD_ZONE
        elif x_hysteresis or y_hysteresis:
            reason = CameraControlReasonCode.HYSTERESIS_TRACKING
        else:
            reason = CameraControlReasonCode.TRACKING
        return CameraControlDecision(
            error_x=yaw,
            error_y=-pitch,
            yaw_velocity=yaw,
            pitch_velocity=pitch,
            yaw_acceleration=yaw_acceleration,
            pitch_acceleration=pitch_acceleration,
            zoom_target=zoom_target,
            zoom_output=self._current_zoom,
            target_locked=True,
            frozen=False,
            x_axis_active=self._x_axis_active,
            y_axis_active=self._y_axis_active,
            uncertainty_score=request.uncertainty_score,
            reason_code=reason,
        )

    def _axis_velocity(
        self,
        error: float,
        previous: float,
        active: bool,
        *,
        gain: float,
        max_velocity: float,
        max_acceleration: float,
        delta_time: float,
    ) -> tuple[float, bool, bool]:
        magnitude = abs(error)
        hysteresis = False
        if active:
            if magnitude <= self.config.dead_zone_exit:
                active = False
                error = 0.0
            else:
                hysteresis = magnitude < self.config.dead_zone_enter
        elif magnitude < self.config.dead_zone_enter:
            error = 0.0
        else:
            active = True
        requested = _clamp(error * gain, -max_velocity, max_velocity)
        low_passed = previous + (requested - previous) * self.config.low_pass_alpha
        max_delta = max_acceleration * delta_time
        output = previous + _clamp(low_passed - previous, -max_delta, max_delta)
        output = _clamp(output, -max_velocity, max_velocity)
        if not active and abs(output) < 1e-9:
            output = 0.0
        return output, active, hysteresis

    def _lost_decision(
        self,
        request: CameraControlRequest,
        zoom_target: float,
        now: float,
        delta_time: float,
    ) -> CameraControlDecision:
        self._zero_motion()
        if self._lost_started_at is None:
            self._lost_started_at = now
        elapsed = max(0.0, now - self._lost_started_at)
        if elapsed <= self.config.zoom_hold_seconds:
            reason = CameraControlReasonCode.TARGET_LOST_ZOOM_HOLD
        else:
            self._current_zoom = _move_towards(
                self._current_zoom,
                self.config.zoom_return_target,
                self.config.zoom_ramp_per_second * delta_time,
            )
            reason = CameraControlReasonCode.TARGET_LOST_ZOOM_RETURN
        return CameraControlDecision(
            error_x=0.0,
            error_y=0.0,
            yaw_velocity=0.0,
            pitch_velocity=0.0,
            yaw_acceleration=0.0,
            pitch_acceleration=0.0,
            zoom_target=zoom_target,
            zoom_output=self._current_zoom,
            target_locked=False,
            frozen=False,
            x_axis_active=False,
            y_axis_active=False,
            uncertainty_score=request.uncertainty_score,
            reason_code=reason,
        )

    def _stopped_decision(
        self,
        request: CameraControlRequest,
        zoom_target: float,
        reason: CameraControlReasonCode,
        *,
        frozen: bool,
    ) -> CameraControlDecision:
        self._zero_motion()
        return CameraControlDecision(
            error_x=0.0,
            error_y=0.0,
            yaw_velocity=0.0,
            pitch_velocity=0.0,
            yaw_acceleration=0.0,
            pitch_acceleration=0.0,
            zoom_target=zoom_target,
            zoom_output=self._current_zoom,
            target_locked=False,
            frozen=frozen,
            x_axis_active=False,
            y_axis_active=False,
            uncertainty_score=request.uncertainty_score,
            reason_code=reason,
        )

    def _zero_motion(self) -> None:
        self._yaw_velocity = 0.0
        self._pitch_velocity = 0.0
        self._x_axis_active = False
        self._y_axis_active = False

    def _delta_time(self, now: float) -> float:
        if self._last_update_at is None or now <= self._last_update_at:
            delta = self.config.nominal_interval_seconds
        else:
            delta = min(now - self._last_update_at, self.config.max_interval_seconds)
        self._last_update_at = now
        return delta


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _move_towards(current: float, target: float, maximum_delta: float) -> float:
    if current < target:
        return min(target, current + maximum_delta)
    return max(target, current - maximum_delta)
