"""Implementation-neutral data contracts for vision pipeline boundaries.

These contracts deliberately do not import YOLO, tracker, GID, ReID, UI, or
transport modules. Phase 1 introduces them alongside the V1.0-alpha.1 pipeline; later
adapters can translate to and from existing implementation-specific objects
without changing current algorithm results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Literal, Mapping


IdentityStatus = Literal["unassigned", "tracking", "coasting", "searching", "lost"]
TargetStatus = Literal["idle", "tracking", "coasting", "searching", "lost", "failed"]
IDENTITY_STATUSES = frozenset({"unassigned", "tracking", "coasting", "searching", "lost"})
TARGET_STATUSES = frozenset({"idle", "tracking", "coasting", "searching", "lost", "failed"})


def _require_non_negative(name: str, value: int | float) -> None:
    if isinstance(value, float):
        _require_finite(name, value)
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_finite(name: str, value: float) -> None:
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")


def _require_unit_interval(name: str, value: float) -> None:
    _require_finite(name, value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Pixel-space box using `(left, top, right, bottom)` coordinates."""

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        for name in ("left", "top", "right", "bottom"):
            _require_finite(name, getattr(self, name))
        if self.right < self.left or self.bottom < self.top:
            raise ValueError("bounding box edges are inverted")

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(frozen=True, slots=True)
class FramePacket:
    """A captured frame plus source and timing metadata."""

    frame_index: int
    timestamp: float
    source_id: str
    image: Any = field(repr=False, compare=False)
    width: int
    height: int
    source_fps: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_non_negative("frame_index", self.frame_index)
        _require_finite("timestamp", self.timestamp)
        if not self.source_id:
            raise ValueError("source_id must not be empty")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("frame dimensions must be positive")
        if self.source_fps is not None:
            _require_finite("source_fps", self.source_fps)
            if self.source_fps <= 0:
                raise ValueError("source_fps must be positive when present")


@dataclass(frozen=True, slots=True)
class Detection:
    """One detector observation before tracker identity is applied."""

    bbox: BoundingBox
    class_id: int
    class_name: str
    confidence: float
    attributes: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_non_negative("class_id", self.class_id)
        _require_unit_interval("confidence", self.confidence)
        if not self.class_name:
            raise ValueError("class_name must not be empty")


@dataclass(frozen=True, slots=True)
class DetectionBatch:
    """Detector output associated with exactly one input frame."""

    frame_index: int
    timestamp: float
    detections: tuple[Detection, ...] = ()
    model_name: str | None = None
    inference_time_ms: float = 0.0

    def __post_init__(self) -> None:
        _require_non_negative("frame_index", self.frame_index)
        _require_finite("timestamp", self.timestamp)
        _require_non_negative("inference_time_ms", self.inference_time_ms)
        if not isinstance(self.detections, tuple):
            object.__setattr__(self, "detections", tuple(self.detections))


@dataclass(frozen=True, slots=True)
class Track:
    """One tracker observation, including V1.0-alpha.1's possible missing LID."""

    local_track_id: int | None
    bbox: BoundingBox
    class_id: int
    class_name: str
    confidence: float
    age_frames: int = 0
    lost_frames: int = 0
    predicted: bool = False

    def __post_init__(self) -> None:
        if self.local_track_id is not None:
            _require_non_negative("local_track_id", self.local_track_id)
        _require_non_negative("class_id", self.class_id)
        _require_unit_interval("confidence", self.confidence)
        _require_non_negative("age_frames", self.age_frames)
        _require_non_negative("lost_frames", self.lost_frames)
        if not self.class_name:
            raise ValueError("class_name must not be empty")


@dataclass(frozen=True, slots=True)
class TrackBatch:
    """Tracker output associated with exactly one detector batch."""

    frame_index: int
    timestamp: float
    tracks: tuple[Track, ...] = ()
    tracker_name: str | None = None
    tracking_time_ms: float = 0.0

    def __post_init__(self) -> None:
        _require_non_negative("frame_index", self.frame_index)
        _require_finite("timestamp", self.timestamp)
        _require_non_negative("tracking_time_ms", self.tracking_time_ms)
        if not isinstance(self.tracks, tuple):
            object.__setattr__(self, "tracks", tuple(self.tracks))


@dataclass(frozen=True, slots=True)
class IdentityState:
    """Long-lived GID state without embedding or persistence details."""

    global_identity_id: int | None
    local_track_id: int | None
    status: IdentityStatus
    class_name: str | None = None
    confidence: float = 0.0
    bbox: BoundingBox | None = None
    lost_frames: int = 0
    reid_score: float | None = None

    def __post_init__(self) -> None:
        if self.status not in IDENTITY_STATUSES:
            raise ValueError(f"unsupported identity status: {self.status}")
        if self.global_identity_id is not None:
            _require_non_negative("global_identity_id", self.global_identity_id)
        if self.local_track_id is not None:
            _require_non_negative("local_track_id", self.local_track_id)
        _require_unit_interval("confidence", self.confidence)
        _require_non_negative("lost_frames", self.lost_frames)
        if self.reid_score is not None:
            _require_unit_interval("reid_score", self.reid_score)


@dataclass(frozen=True, slots=True)
class TargetState:
    """Selected target state consumed by framing and camera control."""

    status: TargetStatus
    global_identity_id: int | None = None
    local_track_id: int | None = None
    bbox: BoundingBox | None = None
    confidence: float = 0.0
    lost_frames: int = 0
    velocity: tuple[float, float] = (0.0, 0.0)
    predicted: bool = False
    safe_to_track: bool = True

    def __post_init__(self) -> None:
        if self.status not in TARGET_STATUSES:
            raise ValueError(f"unsupported target status: {self.status}")
        if self.global_identity_id is not None:
            _require_non_negative("global_identity_id", self.global_identity_id)
        if self.local_track_id is not None:
            _require_non_negative("local_track_id", self.local_track_id)
        _require_unit_interval("confidence", self.confidence)
        _require_non_negative("lost_frames", self.lost_frames)
        if len(self.velocity) != 2:
            raise ValueError("velocity must contain exactly two values")
        _require_finite("velocity x", self.velocity[0])
        _require_finite("velocity y", self.velocity[1])

    @property
    def center(self) -> tuple[float, float] | None:
        return None if self.bbox is None else self.bbox.center


@dataclass(frozen=True, slots=True)
class CameraCommand:
    """Implementation-neutral camera command with normalized image errors."""

    sequence: int
    timestamp_ms: int
    target_locked: bool
    error_x: float = 0.0
    error_y: float = 0.0
    confidence: float = 0.0
    target_id: int | None = None
    zoom_factor: float | None = None
    predicted_target: bool = False

    def __post_init__(self) -> None:
        _require_non_negative("sequence", self.sequence)
        _require_non_negative("timestamp_ms", self.timestamp_ms)
        for name in ("error_x", "error_y"):
            value = getattr(self, name)
            _require_finite(name, value)
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between -1.0 and 1.0")
        _require_unit_interval("confidence", self.confidence)
        if self.target_id is not None:
            _require_non_negative("target_id", self.target_id)
        if self.zoom_factor is not None:
            _require_finite("zoom_factor", self.zoom_factor)
            if self.zoom_factor <= 0:
                raise ValueError("zoom_factor must be positive when present")
