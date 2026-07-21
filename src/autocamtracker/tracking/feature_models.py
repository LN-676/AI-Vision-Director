"""Shared data contracts for the Phase 6 feature-gallery components."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from autocamtracker.vision.detector import TrackedDetection


GalleryType = Literal["master", "pending", "candidate"]


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


@dataclass
class StoredFeature:
    match: FeatureMatch
    embedding: list[float]
