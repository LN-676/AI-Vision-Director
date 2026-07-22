"""Global motion compensation with auditable quality and failure reasons."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import atan2, degrees, hypot, isfinite
from typing import Any, Protocol

from autocamtracker.vision.camera_calibration import CameraCalibrationSubsystem


class GMCReasonCode(str, Enum):
    INITIALIZING = "INITIALIZING"
    ESTIMATED = "ESTIMATED"
    CAMERA_CUT_RESET = "CAMERA_CUT_RESET"
    FRAME_SHAPE_CHANGED = "FRAME_SHAPE_CHANGED"
    INSUFFICIENT_FEATURES = "INSUFFICIENT_FEATURES"
    OPTICAL_FLOW_FAILED = "OPTICAL_FLOW_FAILED"
    AFFINE_ESTIMATION_FAILED = "AFFINE_ESTIMATION_FAILED"
    LOW_INLIER_RATIO = "LOW_INLIER_RATIO"
    EXCESSIVE_TRANSFORM = "EXCESSIVE_TRANSFORM"


@dataclass(frozen=True)
class GMCConfig:
    max_features: int = 500
    quality_level: float = 0.01
    min_feature_distance: float = 8.0
    min_tracked_points: int = 20
    ransac_threshold_px: float = 3.0
    min_inlier_ratio: float = 0.50
    max_translation_ratio: float = 0.25
    max_rotation_degrees: float = 15.0
    max_scale_change: float = 0.15
    exclusion_padding_px: int = 8
    analysis_max_dimension: int = 960

    def __post_init__(self) -> None:
        if self.max_features < 1 or self.min_tracked_points < 3:
            raise ValueError("GMC feature counts must be positive and geometrically valid")
        if not 0.0 < self.quality_level <= 1.0:
            raise ValueError("GMC quality_level must be in (0, 1]")
        if self.min_feature_distance < 0.0 or self.ransac_threshold_px <= 0.0:
            raise ValueError("GMC distance thresholds are invalid")
        if not 0.0 <= self.min_inlier_ratio <= 1.0:
            raise ValueError("GMC min_inlier_ratio must be in [0, 1]")
        if (
            self.max_translation_ratio < 0.0
            or self.max_rotation_degrees < 0.0
            or self.max_scale_change < 0.0
            or self.exclusion_padding_px < 0
            or self.analysis_max_dimension < 0
        ):
            raise ValueError("GMC transform limits, padding, and analysis size cannot be negative")


@dataclass(frozen=True)
class GMCMeasurement:
    affine: tuple[float, float, float, float, float, float]
    tracked_points: int
    inlier_count: int
    residual_px: float

    def __post_init__(self) -> None:
        if len(self.affine) != 6 or not all(isfinite(value) for value in self.affine):
            raise ValueError("GMC affine measurement must contain six finite values")
        if (
            self.tracked_points < 0
            or self.inlier_count < 0
            or self.inlier_count > self.tracked_points
            or self.residual_px < 0.0
            or not isfinite(self.residual_px)
        ):
            raise ValueError("GMC measurement quality metadata is invalid")


@dataclass(frozen=True)
class GMCBackendResult:
    measurement: GMCMeasurement | None
    reason_code: GMCReasonCode


@dataclass(frozen=True)
class GlobalMotionEstimate:
    transform: tuple[tuple[float, float, float], ...]
    compensation_transform: tuple[tuple[float, float, float], ...]
    translation_x: float
    translation_y: float
    rotation_degrees: float
    scale: float
    tracked_points: int
    inlier_count: int
    inlier_ratio: float
    residual_px: float
    reliable: bool
    reason_code: GMCReasonCode
    calibration_profile_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "transform": [list(row) for row in self.transform],
            "compensation_transform": [list(row) for row in self.compensation_transform],
            "translation_x": self.translation_x,
            "translation_y": self.translation_y,
            "rotation_degrees": self.rotation_degrees,
            "scale": self.scale,
            "tracked_points": self.tracked_points,
            "inlier_count": self.inlier_count,
            "inlier_ratio": self.inlier_ratio,
            "residual_px": self.residual_px,
            "reliable": self.reliable,
            "reason_code": self.reason_code.value,
            "calibration_profile_id": self.calibration_profile_id,
        }

    def compensate_point(self, point: tuple[float, float]) -> tuple[float, float]:
        return _transform_point(self.compensation_transform, point)


class GMCBackend(Protocol):
    def estimate(
        self,
        previous_frame: Any,
        current_frame: Any,
        previous_exclusions: tuple[tuple[float, float, float, float], ...],
        current_exclusions: tuple[tuple[float, float, float, float], ...],
        config: GMCConfig,
    ) -> GMCBackendResult: ...


class OpenCVGMCBackend:
    def estimate(
        self,
        previous_frame: Any,
        current_frame: Any,
        previous_exclusions: tuple[tuple[float, float, float, float], ...],
        current_exclusions: tuple[tuple[float, float, float, float], ...],
        config: GMCConfig,
    ) -> GMCBackendResult:
        import cv2
        import numpy as np

        previous_gray = _gray(previous_frame, cv2)
        current_gray = _gray(current_frame, cv2)
        mask = np.full(previous_gray.shape, 255, dtype=np.uint8)
        _mask_boxes(mask, previous_exclusions, config.exclusion_padding_px)
        points = cv2.goodFeaturesToTrack(
            previous_gray,
            maxCorners=config.max_features,
            qualityLevel=config.quality_level,
            minDistance=config.min_feature_distance,
            mask=mask,
        )
        if points is None or len(points) < config.min_tracked_points:
            return GMCBackendResult(None, GMCReasonCode.INSUFFICIENT_FEATURES)
        next_points, status, _ = cv2.calcOpticalFlowPyrLK(
            previous_gray, current_gray, points, None
        )
        if next_points is None or status is None:
            return GMCBackendResult(None, GMCReasonCode.OPTICAL_FLOW_FAILED)
        valid = status.reshape(-1).astype(bool)
        previous_valid = points.reshape(-1, 2)[valid]
        current_valid = next_points.reshape(-1, 2)[valid]
        keep = np.asarray([
            not _inside_boxes(tuple(point), current_exclusions, config.exclusion_padding_px)
            for point in current_valid
        ], dtype=bool)
        previous_valid = previous_valid[keep]
        current_valid = current_valid[keep]
        if len(previous_valid) < config.min_tracked_points:
            return GMCBackendResult(None, GMCReasonCode.INSUFFICIENT_FEATURES)
        affine, inliers = cv2.estimateAffinePartial2D(
            previous_valid,
            current_valid,
            method=cv2.RANSAC,
            ransacReprojThreshold=config.ransac_threshold_px,
        )
        if affine is None or inliers is None:
            return GMCBackendResult(None, GMCReasonCode.AFFINE_ESTIMATION_FAILED)
        inlier_mask = inliers.reshape(-1).astype(bool)
        predicted = cv2.transform(previous_valid.reshape(1, -1, 2), affine).reshape(-1, 2)
        residuals = np.linalg.norm(predicted - current_valid, axis=1)
        residual = float(np.median(residuals[inlier_mask])) if bool(np.any(inlier_mask)) else 0.0
        values = tuple(float(value) for value in affine.reshape(-1))
        return GMCBackendResult(
            GMCMeasurement(
                affine=values,  # type: ignore[arg-type]
                tracked_points=len(previous_valid),
                inlier_count=int(np.count_nonzero(inlier_mask)),
                residual_px=residual,
            ),
            GMCReasonCode.ESTIMATED,
        )


class GlobalMotionCompensator:
    def __init__(
        self,
        config: GMCConfig | None = None,
        *,
        backend: GMCBackend | None = None,
        calibration: CameraCalibrationSubsystem | None = None,
    ) -> None:
        self.config = config or GMCConfig()
        self.backend = backend or OpenCVGMCBackend()
        self.calibration = calibration
        self._previous_frame: Any | None = None
        self._previous_shape: tuple[int, int] | None = None
        self._previous_exclusions: tuple[tuple[float, float, float, float], ...] = ()
        self._next_initial_reason = GMCReasonCode.INITIALIZING

    def reset(self, reason: GMCReasonCode = GMCReasonCode.INITIALIZING) -> None:
        self._previous_frame = None
        self._previous_shape = None
        self._previous_exclusions = ()
        self._next_initial_reason = reason

    def update(
        self,
        frame: Any,
        exclusion_bboxes: list[tuple[float, float, float, float]] | tuple[
            tuple[float, float, float, float], ...
        ] = (),
    ) -> GlobalMotionEstimate:
        calibrated_frame, profile_id = (
            self.calibration.undistort(frame)
            if self.calibration is not None else (frame, None)
        )
        shape = (int(calibrated_frame.shape[0]), int(calibrated_frame.shape[1]))
        analysis_frame, analysis_scale = self._analysis_frame(calibrated_frame, shape)
        exclusions = tuple(
            tuple(float(value) * analysis_scale for value in box)
            for box in exclusion_bboxes
        )
        if self._previous_frame is None:
            reason = self._next_initial_reason
            self._remember(analysis_frame, shape, exclusions)
            self._next_initial_reason = GMCReasonCode.INITIALIZING
            return _empty_estimate(reason, profile_id)
        if shape != self._previous_shape:
            self._remember(analysis_frame, shape, exclusions)
            return _empty_estimate(GMCReasonCode.FRAME_SHAPE_CHANGED, profile_id)
        result = self.backend.estimate(
            self._previous_frame,
            analysis_frame,
            self._previous_exclusions,
            exclusions,
            self.config,
        )
        self._remember(analysis_frame, shape, exclusions)
        if result.measurement is None:
            return _empty_estimate(result.reason_code, profile_id)
        return self._from_measurement(
            self._measurement_at_source_scale(result.measurement, analysis_scale),
            shape,
            profile_id,
        )

    def _analysis_frame(
        self,
        frame: Any,
        shape: tuple[int, int],
    ) -> tuple[Any, float]:
        """Downscale pixels used by optical flow while preserving source coordinates."""
        limit = self.config.analysis_max_dimension
        largest_dimension = max(shape)
        if limit <= 0 or largest_dimension <= limit:
            return frame, 1.0

        scale = limit / largest_dimension
        width = max(1, int(round(shape[1] * scale)))
        height = max(1, int(round(shape[0] * scale)))
        try:
            import cv2

            resized = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        except (TypeError, ValueError, cv2.error):
            # Test doubles and non-array injected frames keep the original path.
            return frame, 1.0
        return resized, scale

    @staticmethod
    def _measurement_at_source_scale(
        measurement: GMCMeasurement,
        analysis_scale: float,
    ) -> GMCMeasurement:
        if analysis_scale == 1.0:
            return measurement
        a, b, tx, c, d, ty = measurement.affine
        return GMCMeasurement(
            (a, b, tx / analysis_scale, c, d, ty / analysis_scale),
            measurement.tracked_points,
            measurement.inlier_count,
            measurement.residual_px / analysis_scale,
        )

    def _remember(self, frame: Any, shape: tuple[int, int], exclusions) -> None:
        self._previous_frame = frame
        self._previous_shape = shape
        self._previous_exclusions = exclusions

    def _from_measurement(
        self,
        measurement: GMCMeasurement,
        shape: tuple[int, int],
        profile_id: str | None,
    ) -> GlobalMotionEstimate:
        a, b, tx, c, d, ty = measurement.affine
        scale = (hypot(a, c) + hypot(b, d)) / 2.0
        rotation = degrees(atan2(c, a))
        transform = ((a, b, tx), (c, d, ty), (0.0, 0.0, 1.0))
        inverse = _invert_affine(transform)
        ratio = measurement.inlier_count / max(1, measurement.tracked_points)
        height, width = shape
        excessive = (
            hypot(tx, ty) > hypot(width, height) * self.config.max_translation_ratio
            or abs(rotation) > self.config.max_rotation_degrees
            or abs(scale - 1.0) > self.config.max_scale_change
        )
        if ratio < self.config.min_inlier_ratio:
            reliable = False
            reason = GMCReasonCode.LOW_INLIER_RATIO
        elif excessive or inverse is None:
            reliable = False
            reason = GMCReasonCode.EXCESSIVE_TRANSFORM
        else:
            reliable = True
            reason = GMCReasonCode.ESTIMATED
        compensation = inverse or _identity_matrix()
        values = (tx, ty, rotation, scale, ratio, measurement.residual_px)
        if not all(isfinite(value) for value in values):
            return _empty_estimate(GMCReasonCode.AFFINE_ESTIMATION_FAILED, profile_id)
        return GlobalMotionEstimate(
            transform=transform,
            compensation_transform=compensation,
            translation_x=tx,
            translation_y=ty,
            rotation_degrees=rotation,
            scale=scale,
            tracked_points=measurement.tracked_points,
            inlier_count=measurement.inlier_count,
            inlier_ratio=ratio,
            residual_px=measurement.residual_px,
            reliable=reliable,
            reason_code=reason,
            calibration_profile_id=profile_id,
        )


def _empty_estimate(
    reason: GMCReasonCode, profile_id: str | None
) -> GlobalMotionEstimate:
    identity = _identity_matrix()
    return GlobalMotionEstimate(
        identity, identity, 0.0, 0.0, 0.0, 1.0, 0, 0, 0.0, 0.0, False,
        reason, profile_id,
    )


def _identity_matrix() -> tuple[tuple[float, float, float], ...]:
    return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _invert_affine(matrix):
    a, b, tx = matrix[0]
    c, d, ty = matrix[1]
    determinant = a * d - b * c
    if abs(determinant) <= 1e-12:
        return None
    inverse_a, inverse_b = d / determinant, -b / determinant
    inverse_c, inverse_d = -c / determinant, a / determinant
    return (
        (inverse_a, inverse_b, -(inverse_a * tx + inverse_b * ty)),
        (inverse_c, inverse_d, -(inverse_c * tx + inverse_d * ty)),
        (0.0, 0.0, 1.0),
    )


def _transform_point(matrix, point: tuple[float, float]) -> tuple[float, float]:
    x, y = point
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2],
    )


def _gray(frame, cv2):
    return frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _mask_boxes(mask, boxes, padding: int) -> None:
    height, width = mask.shape[:2]
    for x1, y1, x2, y2 in boxes:
        left = max(0, int(x1) - padding)
        top = max(0, int(y1) - padding)
        right = min(width, int(x2) + padding)
        bottom = min(height, int(y2) + padding)
        mask[top:bottom, left:right] = 0


def _inside_boxes(point, boxes, padding: int) -> bool:
    x, y = point
    return any(
        x1 - padding <= x <= x2 + padding and y1 - padding <= y <= y2 + padding
        for x1, y1, x2, y2 in boxes
    )
