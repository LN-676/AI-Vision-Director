"""Detection-to-identity ranking using encoded crops and a vector index."""

from __future__ import annotations

from autocamtracker.tracking.crop_quality_assessor import CropQualityAssessor
from autocamtracker.tracking.embedding_encoder import EmbeddingEncoder
from autocamtracker.tracking.feature_models import DetectionFeatureMatch
from autocamtracker.tracking.feature_repository import FeatureRepository
from autocamtracker.tracking.vector_index import VectorIndex
from autocamtracker.vision.detector import TrackedDetection


class IdentityMatcher:
    def __init__(self, repository: FeatureRepository, assessor: CropQualityAssessor,
                 encoder: EmbeddingEncoder, index: VectorIndex) -> None:
        self.repository = repository
        self.assessor = assessor
        self.encoder = encoder
        self.index = index

    def rank_detections_for_vehicle(self, vehicle_id: int, detections: list[TrackedDetection], frame,
                                    top_k: int = 5) -> list[DetectionFeatureMatch]:
        if not self.repository.has_master_features(vehicle_id):
            return []
        valid = [detection for detection in detections if self.assessor.assess(frame, detection.bbox).accepted]
        embeddings = self.encoder.encode_batch(frame, valid, use_cache=True)
        ranked = []
        for detection, embedding in zip(valid, embeddings):
            if embedding is None:
                continue
            matches = self.index.top_k(embedding, "master", top_k, vehicle_id)
            if matches:
                ranked.append(DetectionFeatureMatch(detection, matches[0].score, matches))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked
