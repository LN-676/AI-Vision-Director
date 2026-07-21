"""Compatibility façade composing the Phase 6 feature-gallery components."""

from __future__ import annotations

from pathlib import Path
from time import time
from typing import Any, Literal
from uuid import uuid4

from autocamtracker.tracking.crop_quality_assessor import CropQualityAssessor
from autocamtracker.tracking.embedding_encoder import EmbeddingEncoder
from autocamtracker.tracking.feature_models import (
    CropQuality,
    DetectionFeatureMatch,
    FeatureAddResult,
    FeatureMatch,
    FeatureSnapshot,
    GalleryRollbackEvent,
    GalleryRollbackResult,
    GalleryType,
    GalleryWriteContext,
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
    MIN_LOCKED_IDENTITY_SCORE = 0.84

    def __init__(self, db_path: Path | str, reid_model_path: str = "reid/yolo26s-reid.onnx",
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

    def import_jpg(
        self,
        vehicle_id: int,
        jpg_path: Path | str,
        class_name: str = "car",
        *,
        context: GalleryWriteContext | None = None,
    ) -> FeatureAddResult:
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
        return self.add_master_feature(vehicle_id, detection, frame, context=context)

    def add_master_feature(
        self, vehicle_id: int, detection: TrackedDetection, frame, *,
        context: GalleryWriteContext | None = None,
    ) -> FeatureAddResult:
        return self._add_feature(vehicle_id, detection, frame, "master", context)

    def add_pending_feature(
        self, vehicle_id: int, detection: TrackedDetection, frame, *,
        context: GalleryWriteContext | None = None,
    ) -> FeatureAddResult:
        return self._add_feature(vehicle_id, detection, frame, "pending", context)

    def add_candidate_feature(
        self, vehicle_id: int, detection: TrackedDetection, frame, *,
        context: GalleryWriteContext | None = None,
    ) -> FeatureAddResult:
        return self._add_feature(vehicle_id, detection, frame, "candidate", context)

    def _add_feature(
        self,
        vehicle_id: int,
        detection: TrackedDetection,
        frame,
        gallery_type: GalleryType,
        context: GalleryWriteContext | None,
    ) -> FeatureAddResult:
        gate_reason = self._write_gate_reason(vehicle_id, detection, context)
        if gate_reason is not None:
            rejected_quality = CropQuality(False, 0.0, gate_reason, 0, 0, 0.0, 0.0)
            return FeatureAddResult(
                False, vehicle_id, gallery_type, None, rejected_quality, reason=gate_reason
            )
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
        assert context is not None
        write_id = uuid4().hex
        provenance = {
            "write_id": write_id,
            "source": context.source,
            "captured_at": context.captured_at,
            "global_vehicle_id": context.global_vehicle_id,
            "local_track_id": context.local_track_id,
            "frame_index": detection.frame_index,
            "detection_track_id": detection.track_id,
            "detection_class": detection.class_name,
            "detection_confidence": detection.confidence,
            "identity_state": context.identity_state,
            "identity_reason_code": context.identity_reason_code,
            "identity_score": context.identity_score,
            "identity_sub_scores": dict(context.identity_sub_scores),
            "decision_accepted": context.decision_accepted,
            "motor_safe_to_track": context.motor_safe_to_track,
            "gallery_type": gallery_type,
            "quality_score": quality.score,
            "duplicate_score": duplicate_score,
            "reid_model_path": self.reid_model_path,
        }
        feature_id = self.repository.insert(
            vehicle_id,
            gallery_type,
            detection,
            quality,
            embedding,
            duplicate_score,
            self.crop_quality_assessor.encode_jpeg(frame, detection.bbox),
            self.reid_model_path,
            provenance,
        )
        self.vector_index.invalidate()
        if gallery_type == "master" and self.repository.prune_master(vehicle_id, self.gallery_policy.master_feature_limit):
            self.vector_index.invalidate()
        reason = "added to master gallery" if gallery_type == "master" else "added"
        return FeatureAddResult(
            True, vehicle_id, gallery_type, feature_id, quality, duplicate_score, reason, write_id
        )

    def _write_gate_reason(
        self,
        vehicle_id: int,
        detection: TrackedDetection,
        context: GalleryWriteContext | None,
    ) -> str | None:
        if context is None:
            return "gallery write rejected: identity provenance is required"
        if context.identity_state != "LOCKED":
            return f"gallery write rejected: identity state {context.identity_state or 'NONE'} is not LOCKED"
        if not context.decision_accepted:
            return "gallery write rejected: identity decision was not accepted"
        if context.identity_score < self.MIN_LOCKED_IDENTITY_SCORE:
            return (
                f"gallery write rejected: identity score {context.identity_score:.2f} is below "
                f"{self.MIN_LOCKED_IDENTITY_SCORE:.2f}"
            )
        if not context.motor_safe_to_track:
            return "gallery write rejected: identity lock is not motor-safe"
        if context.global_vehicle_id != vehicle_id:
            return "gallery write rejected: provenance GID does not match destination GID"
        if (
            detection.track_id is not None
            and context.local_track_id != detection.track_id
        ):
            return "gallery write rejected: provenance LID does not match detection LID"
        return None

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

    def feature_snapshots(
        self,
        vehicle_id: int,
        gallery_type: GalleryType = "master",
        *,
        include_rolled_back: bool = False,
    ) -> list[FeatureSnapshot]:
        return self.repository.snapshots(
            vehicle_id, gallery_type, include_rolled_back=include_rolled_back
        )

    def delete_features(self, feature_ids: list[int], vehicle_id: int | None = None) -> int:
        deleted = self.repository.delete_features(feature_ids, vehicle_id)
        self.vector_index.invalidate()
        return deleted

    def rollback_features(
        self,
        feature_ids: list[int],
        *,
        reason: str,
        actor: str,
        vehicle_id: int | None = None,
    ) -> GalleryRollbackResult:
        result = self.repository.rollback_features(
            feature_ids, reason=reason, actor=actor, vehicle_id=vehicle_id
        )
        if result.rolled_back_count:
            self.vector_index.invalidate()
        return result

    def rollback_write(
        self, write_id: str, *, reason: str, actor: str
    ) -> GalleryRollbackResult:
        result = self.repository.rollback_write(write_id, reason=reason, actor=actor)
        if result.rolled_back_count:
            self.vector_index.invalidate()
        return result

    def rollback_events(self, limit: int = 100) -> list[GalleryRollbackEvent]:
        return self.repository.rollback_events(limit)

    def first_feature_crop_jpeg(self, vehicle_id: int) -> bytes | None:
        return self.repository.first_crop_jpeg(vehicle_id)

    def assess_crop_quality(self, frame, bbox: tuple[float, float, float, float]) -> CropQuality:
        return self.crop_quality_assessor.assess(frame, bbox)

    @staticmethod
    def cosine_similarity(first: Any | None, second: Any | None) -> float:
        return VectorIndex.cosine_similarity(first, second)


__all__ = [
    "CropQuality", "DetectionFeatureMatch", "FaissFeatureIndex", "FeatureAddResult", "FeatureGallery",
    "FeatureIndexBackend", "FeatureMatch", "FeatureSnapshot", "GalleryRollbackEvent",
    "GalleryRollbackResult", "GalleryType", "GalleryWriteContext", "MilvusFeatureIndex",
    "QdrantFeatureIndex",
]
