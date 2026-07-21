"""Compatibility façade composing the Phase 6 feature-gallery components."""

from __future__ import annotations

from pathlib import Path
from time import time
from typing import Any, Literal

from autocamtracker.tracking.crop_quality_assessor import CropQualityAssessor
from autocamtracker.tracking.embedding_encoder import EmbeddingEncoder
from autocamtracker.tracking.feature_models import (
    CropQuality, DetectionFeatureMatch, FeatureAddResult, FeatureMatch, FeatureSnapshot, GalleryType,
)
from autocamtracker.tracking.feature_repository import FeatureRepository
from autocamtracker.tracking.gallery_policy import GalleryPolicy
from autocamtracker.tracking import identity_matcher as feature_matching
from autocamtracker.tracking.vector_index import (
    FaissFeatureIndex, FeatureIndexBackend, MilvusFeatureIndex, QdrantFeatureIndex, VectorIndex,
)
from autocamtracker.vision.detector import TrackedDetection


class FeatureGallery:
    """Stable API over storage, encoding, indexing, policy, quality, and matching."""

    MASTER_FEATURE_LIMIT = 500

    def __init__(self, db_path: Path | str, reid_model_path: str = "yolo26s-reid.onnx",
                 duplicate_threshold: float = 0.985, min_match_score: float = 0.72) -> None:
        self.repository = FeatureRepository(db_path)
        self.crop_quality_assessor = CropQualityAssessor()
        self.embedding_encoder = EmbeddingEncoder(reid_model_path, self.crop_quality_assessor)
        self.vector_index = VectorIndex(self.repository)
        self.gallery_policy = GalleryPolicy(duplicate_threshold, min_match_score, self.MASTER_FEATURE_LIMIT)
        self.identity_matcher = feature_matching.IdentityMatcher(
            self.repository, self.crop_quality_assessor, self.embedding_encoder, self.vector_index
        )

    @property
    def db_path(self): return self.repository.db_path
    @property
    def connection(self): return self.repository.connection
    @property
    def reid_model_path(self): return self.embedding_encoder.model_path
    @property
    def embedding_extractor(self): return self.embedding_encoder.extractor
    @embedding_extractor.setter
    def embedding_extractor(self, value): self.embedding_encoder.extractor = value
    @property
    def duplicate_threshold(self): return self.gallery_policy.duplicate_threshold
    @duplicate_threshold.setter
    def duplicate_threshold(self, value): self.gallery_policy.duplicate_threshold = value
    @property
    def min_match_score(self): return self.gallery_policy.min_match_score
    @min_match_score.setter
    def min_match_score(self, value): self.gallery_policy.min_match_score = value

    def close(self) -> None:
        self.reset_runtime_cache()
        self.repository.close()

    def reset_runtime_cache(self) -> None:
        self.embedding_encoder.reset_cache()
        self.vector_index.invalidate()

    def set_reid_model(self, model_path: str) -> None:
        self.embedding_encoder.set_model(model_path)

    def preload_embedding(self) -> bool:
        return self.embedding_encoder.preload()

    def import_jpg(self, vehicle_id: int, jpg_path: Path | str, class_name: str = "car") -> FeatureAddResult:
        import cv2
        path = Path(jpg_path).expanduser()
        if path.suffix.lower() not in {".jpg", ".jpeg"}:
            raise ValueError("Feature imports must use JPG files")
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"Unable to decode JPG feature: {path}")
        height, width = frame.shape[:2]
        detection = TrackedDetection(None, (0.0, 0.0, float(width), float(height)), -1, class_name, 1.0,
            (width / 2.0, height / 2.0), int(time() * 1000), time(), "botsort")
        return self.add_master_feature(vehicle_id, detection, frame)

    def add_master_feature(self, vehicle_id: int, detection: TrackedDetection, frame) -> FeatureAddResult:
        return self._add_feature(vehicle_id, detection, frame, "master")

    def add_pending_feature(self, vehicle_id: int, detection: TrackedDetection, frame) -> FeatureAddResult:
        return self._add_feature(vehicle_id, detection, frame, "pending")

    def add_candidate_feature(self, vehicle_id: int, detection: TrackedDetection, frame) -> FeatureAddResult:
        return self._add_feature(vehicle_id, detection, frame, "candidate")

    def _add_feature(self, vehicle_id: int, detection: TrackedDetection, frame, gallery_type: GalleryType) -> FeatureAddResult:
        quality = self.crop_quality_assessor.assess(frame, detection.bbox)
        if not quality.accepted:
            return FeatureAddResult(False, vehicle_id, gallery_type, None, quality, reason=quality.reason)
        embedding = self.embedding_encoder.encode(frame, detection)
        if embedding is None:
            return FeatureAddResult(False, vehicle_id, gallery_type, None, quality,
                reason="ReID model is unavailable or failed to extract a feature")
        matches = self.vector_index.top_k(embedding, gallery_type, 1, vehicle_id)
        duplicate_score = matches[0].score if matches else None
        rejection = self.gallery_policy.rejection_reason(gallery_type, quality, duplicate_score)
        if rejection:
            return FeatureAddResult(False, vehicle_id, gallery_type, None, quality, duplicate_score, rejection)
        feature_id = self.repository.insert(vehicle_id, gallery_type, detection, quality, embedding,
            duplicate_score, self.crop_quality_assessor.encode_jpeg(frame, detection.bbox), self.reid_model_path)
        self.vector_index.invalidate()
        if gallery_type == "master" and self.repository.prune_master(vehicle_id, self.gallery_policy.master_feature_limit):
            self.vector_index.invalidate()
        reason = "added to master gallery" if gallery_type == "master" else "added"
        return FeatureAddResult(True, vehicle_id, gallery_type, feature_id, quality, duplicate_score, reason)

    def match_top_k(self, query_embedding: list[float], gallery_type: GalleryType = "master", top_k: int = 5,
                    vehicle_id: int | None = None) -> list[FeatureMatch]:
        return self.vector_index.top_k(query_embedding, gallery_type, top_k, vehicle_id)

    def rank_detections_for_vehicle(self, vehicle_id: int, detections: list[TrackedDetection], frame,
                                    top_k: int = 5) -> list[DetectionFeatureMatch]:
        return self.identity_matcher.rank_detections_for_vehicle(vehicle_id, detections, frame, top_k)

    def has_master_features(self, vehicle_id: int) -> bool: return self.repository.has_master_features(vehicle_id)
    def dominant_master_class(self, vehicle_id: int) -> str | None: return self.repository.dominant_master_class(vehicle_id)
    def summary_by_vehicle(self) -> dict[int, dict[str, int]]: return self.repository.summary_by_vehicle()
    def reid_model_labels_by_vehicle(self, gallery_type: GalleryType = "master") -> dict[int, str]:
        return self.repository.model_labels_by_vehicle(gallery_type)

    def delete_vehicle_features(self, vehicle_id: int) -> int:
        deleted = self.repository.delete_vehicle_features(vehicle_id)
        self.vector_index.invalidate()
        return deleted

    def feature_snapshots(self, vehicle_id: int, gallery_type: GalleryType = "master") -> list[FeatureSnapshot]:
        return self.repository.snapshots(vehicle_id, gallery_type)

    def delete_features(self, feature_ids: list[int], vehicle_id: int | None = None) -> int:
        deleted = self.repository.delete_features(feature_ids, vehicle_id)
        self.vector_index.invalidate()
        return deleted

    def first_feature_crop_jpeg(self, vehicle_id: int) -> bytes | None:
        return self.repository.first_crop_jpeg(vehicle_id)

    def assess_crop_quality(self, frame, bbox: tuple[float, float, float, float]) -> CropQuality:
        return self.crop_quality_assessor.assess(frame, bbox)

    @staticmethod
    def cosine_similarity(first: Any | None, second: Any | None) -> float:
        return VectorIndex.cosine_similarity(first, second)


__all__ = [
    "CropQuality", "DetectionFeatureMatch", "FaissFeatureIndex", "FeatureAddResult", "FeatureGallery",
    "FeatureIndexBackend", "FeatureMatch", "FeatureSnapshot", "GalleryType", "MilvusFeatureIndex",
    "QdrantFeatureIndex",
]
