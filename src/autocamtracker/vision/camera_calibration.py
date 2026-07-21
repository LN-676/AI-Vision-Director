"""Versioned camera calibration profiles and OpenCV calibration backend."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from math import isfinite
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import time
from typing import Any, Iterable, Protocol


CALIBRATION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CameraCalibration:
    profile_id: str
    camera_name: str
    image_width: int
    image_height: int
    fx: float
    fy: float
    cx: float
    cy: float
    distortion_coefficients: tuple[float, ...]
    rms_reprojection_error: float
    calibrated_at: float
    calibration_views: int
    lens_model: str = "pinhole"
    source: str = "chessboard"

    def __post_init__(self) -> None:
        numeric = (
            self.fx, self.fy, self.cx, self.cy, self.rms_reprojection_error,
            self.calibrated_at, *self.distortion_coefficients,
        )
        if not self.profile_id or not self.camera_name:
            raise ValueError("calibration profile_id and camera_name are required")
        if self.image_width <= 0 or self.image_height <= 0:
            raise ValueError("calibration image dimensions must be positive")
        if self.fx <= 0.0 or self.fy <= 0.0:
            raise ValueError("camera focal lengths must be positive")
        if len(self.distortion_coefficients) < 4:
            raise ValueError("camera calibration requires at least four distortion coefficients")
        if not all(isfinite(float(value)) for value in numeric):
            raise ValueError("camera calibration values must be finite")
        if self.rms_reprojection_error < 0.0 or self.calibration_views < 1:
            raise ValueError("camera calibration quality metadata is invalid")
        if self.lens_model not in {"pinhole", "fisheye"}:
            raise ValueError("lens_model must be pinhole or fisheye")
        object.__setattr__(
            self,
            "distortion_coefficients",
            tuple(float(value) for value in self.distortion_coefficients),
        )

    @property
    def camera_matrix(self) -> tuple[tuple[float, float, float], ...]:
        return ((self.fx, 0.0, self.cx), (0.0, self.fy, self.cy), (0.0, 0.0, 1.0))

    def scaled_to(self, width: int, height: int) -> "CameraCalibration":
        if width <= 0 or height <= 0:
            raise ValueError("scaled calibration dimensions must be positive")
        scale_x = width / self.image_width
        scale_y = height / self.image_height
        return replace(
            self,
            image_width=width,
            image_height=height,
            fx=self.fx * scale_x,
            fy=self.fy * scale_y,
            cx=self.cx * scale_x,
            cy=self.cy * scale_y,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "camera_name": self.camera_name,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "distortion_coefficients": list(self.distortion_coefficients),
            "rms_reprojection_error": self.rms_reprojection_error,
            "calibrated_at": self.calibrated_at,
            "calibration_views": self.calibration_views,
            "lens_model": self.lens_model,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CameraCalibration":
        return cls(
            profile_id=str(payload["profile_id"]),
            camera_name=str(payload["camera_name"]),
            image_width=int(payload["image_width"]),
            image_height=int(payload["image_height"]),
            fx=float(payload["fx"]),
            fy=float(payload["fy"]),
            cx=float(payload["cx"]),
            cy=float(payload["cy"]),
            distortion_coefficients=tuple(
                float(value) for value in payload["distortion_coefficients"]
            ),
            rms_reprojection_error=float(payload["rms_reprojection_error"]),
            calibrated_at=float(payload["calibrated_at"]),
            calibration_views=int(payload["calibration_views"]),
            lens_model=str(payload.get("lens_model", "pinhole")),
            source=str(payload.get("source", "chessboard")),
        )


class CameraCalibrationStore:
    """Atomic JSON persistence for named calibration profiles."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def list_profiles(self) -> list[CameraCalibration]:
        payload = self._read_payload()
        return [CameraCalibration.from_dict(item) for item in payload["profiles"]]

    def get(self, profile_id: str) -> CameraCalibration | None:
        return next(
            (item for item in self.list_profiles() if item.profile_id == profile_id), None
        )

    def save(self, calibration: CameraCalibration) -> None:
        profiles = {
            item.profile_id: item for item in self.list_profiles()
        }
        profiles[calibration.profile_id] = calibration
        self._write_profiles(sorted(profiles.values(), key=lambda item: item.profile_id))

    def delete(self, profile_id: str) -> bool:
        profiles = self.list_profiles()
        remaining = [item for item in profiles if item.profile_id != profile_id]
        if len(remaining) == len(profiles):
            return False
        self._write_profiles(remaining)
        return True

    def _read_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": CALIBRATION_SCHEMA_VERSION, "profiles": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if int(payload.get("schema_version", 0)) != CALIBRATION_SCHEMA_VERSION:
            raise ValueError("unsupported camera calibration schema version")
        if not isinstance(payload.get("profiles"), list):
            raise ValueError("camera calibration profiles must be a list")
        return payload

    def _write_profiles(self, profiles: list[CameraCalibration]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "profiles": [item.to_dict() for item in profiles],
        }
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(self.path)


class CameraCalibrationBackend(Protocol):
    def calibrate_chessboard(
        self,
        frames: Iterable[Any],
        *,
        profile_id: str,
        camera_name: str,
        board_size: tuple[int, int],
        square_size: float,
        min_views: int,
    ) -> CameraCalibration: ...

    def undistort(self, frame: Any, calibration: CameraCalibration) -> Any: ...


class OpenCVCameraCalibrationBackend:
    def calibrate_chessboard(
        self,
        frames: Iterable[Any],
        *,
        profile_id: str,
        camera_name: str,
        board_size: tuple[int, int] = (9, 6),
        square_size: float = 1.0,
        min_views: int = 8,
    ) -> CameraCalibration:
        import cv2
        import numpy as np

        columns, rows = board_size
        if columns < 2 or rows < 2 or square_size <= 0.0:
            raise ValueError("invalid chessboard geometry")
        template = np.zeros((rows * columns, 3), np.float32)
        template[:, :2] = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2)
        template *= float(square_size)
        object_points = []
        image_points = []
        image_size = None
        criteria = (
            cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
            30,
            0.001,
        )
        for frame in frames:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            current_size = (int(gray.shape[1]), int(gray.shape[0]))
            if image_size is not None and current_size != image_size:
                raise ValueError("calibration frames must have one resolution")
            image_size = current_size
            found, corners = cv2.findChessboardCorners(gray, board_size)
            if not found:
                continue
            refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            object_points.append(template.copy())
            image_points.append(refined)
        if image_size is None or len(image_points) < min_views:
            raise ValueError(
                f"camera calibration requires at least {min_views} valid chessboard views"
            )
        rms, matrix, distortion, _, _ = cv2.calibrateCamera(
            object_points, image_points, image_size, None, None
        )
        return CameraCalibration(
            profile_id=profile_id,
            camera_name=camera_name,
            image_width=image_size[0],
            image_height=image_size[1],
            fx=float(matrix[0, 0]),
            fy=float(matrix[1, 1]),
            cx=float(matrix[0, 2]),
            cy=float(matrix[1, 2]),
            distortion_coefficients=tuple(float(value) for value in distortion.reshape(-1)),
            rms_reprojection_error=float(rms),
            calibrated_at=time(),
            calibration_views=len(image_points),
        )

    def undistort(self, frame: Any, calibration: CameraCalibration) -> Any:
        import cv2
        import numpy as np

        height, width = frame.shape[:2]
        scaled = calibration.scaled_to(width, height)
        matrix = np.asarray(scaled.camera_matrix, dtype=np.float64)
        distortion = np.asarray(scaled.distortion_coefficients, dtype=np.float64)
        if scaled.lens_model == "fisheye":
            return cv2.fisheye.undistortImage(frame, matrix, distortion, Knew=matrix)
        return cv2.undistort(frame, matrix, distortion)


class CameraCalibrationSubsystem:
    def __init__(
        self,
        store: CameraCalibrationStore,
        backend: CameraCalibrationBackend | None = None,
    ) -> None:
        self.store = store
        self.backend = backend or OpenCVCameraCalibrationBackend()
        self.active_profile_id: str | None = None

    @property
    def active_calibration(self) -> CameraCalibration | None:
        return (
            self.store.get(self.active_profile_id)
            if self.active_profile_id is not None else None
        )

    def activate(self, profile_id: str | None) -> CameraCalibration | None:
        if profile_id is None:
            self.active_profile_id = None
            return None
        calibration = self.store.get(profile_id)
        if calibration is None:
            raise KeyError(f"unknown camera calibration profile: {profile_id}")
        self.active_profile_id = profile_id
        return calibration

    def calibrate_chessboard(self, frames: Iterable[Any], **kwargs: Any) -> CameraCalibration:
        calibration = self.backend.calibrate_chessboard(frames, **kwargs)
        self.store.save(calibration)
        return calibration

    def undistort(self, frame: Any) -> tuple[Any, str | None]:
        calibration = self.active_calibration
        if calibration is None:
            return frame, None
        return self.backend.undistort(frame, calibration), calibration.profile_id
