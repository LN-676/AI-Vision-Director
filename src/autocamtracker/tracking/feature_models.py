"""Shared data contracts for the Phase 6 feature-gallery components."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from time import time
from typing import Any, Literal, Mapping

from autocamtracker.vision.detector import TrackedDetection


GalleryType = Literal["master", "pending", "candidate"]


@dataclass(frozen=True)
class GalleryWriteContext:
    """Identity evidence required before any embedding can enter a gallery."""

    source: str
    global_vehicle_id: int | None
    local_track_id: int | None
    identity_state: str | None
    identity_reason_code: str
    identity_score: float
    identity_sub_scores: Mapping[str, float] = field(default_factory=dict)
    decision_accepted: bool = False
    motor_safe_to_track: bool = False
    captured_at: float = field(default_factory=time)

    def __post_init__(self) -> None:
        score = float(self.identity_score)
        captured_at = float(self.captured_at)
        sub_scores = {
            str(name): float(value) for name, value in self.identity_sub_scores.items()
        }
        if not self.source or not self.identity_reason_code:
            raise ValueError("gallery write provenance source and reason code are required")
        if not isfinite(score) or not isfinite(captured_at):
            raise ValueError("gallery write provenance scores and timestamps must be finite")
        if any(not isfinite(value) for value in sub_scores.values()):
            raise ValueError("gallery write provenance sub-scores must be finite")
        object.__setattr__(self, "identity_score", score)
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "identity_sub_scores", sub_scores)

    @classmethod
    def from_identity_manager(cls, manager: Any, *, source: str) -> "GalleryWriteContext":
        decision = getattr(manager, "last_identity_decision", None)
        state = getattr(manager, "identity_state", None)
        reason_code = getattr(decision, "reason_code", None)
        return cls(
            source=source,
            global_vehicle_id=getattr(manager, "selected_global_vehicle_id", None),
            local_track_id=getattr(manager, "selected_local_track_id", None),
            identity_state=getattr(state, "value", state),
            identity_reason_code=(
                getattr(reason_code, "value", None) or str(reason_code or "UNKNOWN")
            ),
            identity_score=float(getattr(decision, "score", 0.0) or 0.0),
            identity_sub_scores=dict(getattr(decision, "sub_scores", {}) or {}),
            decision_accepted=bool(getattr(decision, "accepted", False)),
            motor_safe_to_track=bool(getattr(manager, "motor_safe_to_track", False)),
        )


@dataclass
class CropQuality:
    accepted: bool
    score: float
    reason: str
    width: int
    height: int
    sharpness: float
    brightness: float


@dataclass
class FeatureAddResult:
    accepted: bool
    vehicle_id: int
    gallery_type: GalleryType
    feature_id: int | None
    quality: CropQuality
    duplicate_score: float | None = None
    reason: str = ""
    provenance_write_id: str | None = None


@dataclass
class FeatureMatch:
    feature_id: int
    vehicle_id: int
    gallery_type: GalleryType
    score: float
    quality_score: float
    frame_index: int


@dataclass
class DetectionFeatureMatch:
    detection: TrackedDetection
    score: float
    matches: list[FeatureMatch]


@dataclass
class FeatureSnapshot:
    feature_id: int
    vehicle_id: int
    gallery_type: GalleryType
    created_at: float
    frame_index: int
    track_id: int | None
    quality_score: float
    duplicate_score: float | None
    crop_jpeg: bytes | None
    metadata: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)
    active: bool = True
    rolled_back_at: float | None = None
    rollback_reason: str | None = None


@dataclass
class StoredFeature:
    match: FeatureMatch
    embedding: list[float]


@dataclass(frozen=True)
class GalleryRollbackResult:
    event_id: int | None
    feature_ids: tuple[int, ...]
    rolled_back_count: int
    reason: str


@dataclass(frozen=True)
class GalleryRollbackEvent:
    event_id: int
    created_at: float
    actor: str
    reason: str
    feature_ids: tuple[int, ...]
