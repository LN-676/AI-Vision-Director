"""In-process vector index with optional NumPy acceleration."""

from __future__ import annotations

from typing import Any, Protocol

from autocamtracker.tracking.feature_models import FeatureMatch, GalleryType, StoredFeature
from autocamtracker.tracking.feature_repository import FeatureRepository


class FeatureIndexBackend(Protocol):
    name: str
    def top_k(self, query_embedding: list[float], gallery_type: GalleryType, top_k: int,
              vehicle_id: int | None = None) -> list[FeatureMatch]: ...


class VectorIndex:
    name = "numpy"

    def __init__(self, repository: FeatureRepository) -> None:
        self.repository = repository
        self._cache: dict[tuple[GalleryType, int | None], list[StoredFeature]] = {}

    def invalidate(self) -> None:
        self._cache.clear()

    def top_k(self, query_embedding: list[float], gallery_type: GalleryType = "master", top_k: int = 5,
        vehicle_id: int | None = None) -> list[FeatureMatch]:
        key = (gallery_type, vehicle_id)
        features = self._cache.get(key)
        if features is None:
            features = self.repository.stored_features(gallery_type, vehicle_id)
            self._cache[key] = features
        if not query_embedding or not features:
            return []
        numpy_matches = self._top_k_numpy(query_embedding, features, top_k)
        if numpy_matches is not None:
            return numpy_matches
        scored = [(self.cosine_similarity(query_embedding, feature.embedding), feature) for feature in features]
        scored.sort(key=lambda item: item[0], reverse=True)
        return [FeatureMatch(item.match.feature_id, item.match.vehicle_id, item.match.gallery_type, score,
            item.match.quality_score, item.match.frame_index) for score, item in scored[:max(1, top_k)] if score > 0.0]

    @staticmethod
    def _top_k_numpy(query_embedding: list[float], features: list[StoredFeature],
                     top_k: int) -> list[FeatureMatch] | None:
        try:
            import numpy as np
        except ImportError:
            return None
        query = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
        valid = [feature for feature in features if len(feature.embedding) == query.size]
        if query.size == 0 or not valid:
            return []
        matrix = np.asarray([feature.embedding for feature in valid], dtype=np.float32)
        query_norm = float(np.linalg.norm(query))
        row_norms = np.linalg.norm(matrix, axis=1)
        usable = row_norms > 1e-12
        if query_norm <= 1e-12 or not bool(np.any(usable)):
            return []
        scores = np.zeros(len(valid), dtype=np.float32)
        scores[usable] = matrix[usable].dot(query) / (row_norms[usable] * query_norm)
        scores = np.clip(scores, 0.0, 1.0)
        limit = max(1, min(int(top_k), len(valid)))
        indices = np.argsort(-scores)[:limit]
        return [FeatureMatch(valid[int(index)].match.feature_id, valid[int(index)].match.vehicle_id,
            valid[int(index)].match.gallery_type, float(scores[int(index)]),
            valid[int(index)].match.quality_score, valid[int(index)].match.frame_index)
            for index in indices if float(scores[int(index)]) > 0.0]

    @staticmethod
    def cosine_similarity(first: Any | None, second: Any | None) -> float:
        if first is None or second is None:
            return 0.0
        first_values = [float(value) for value in (first.tolist() if hasattr(first, "tolist") else first)]
        second_values = [float(value) for value in (second.tolist() if hasattr(second, "tolist") else second)]
        if len(first_values) != len(second_values) or not first_values:
            return 0.0
        numerator = sum(a * b for a, b in zip(first_values, second_values))
        first_norm = sum(value * value for value in first_values) ** 0.5
        second_norm = sum(value * value for value in second_values) ** 0.5
        return max(0.0, min(1.0, numerator / (first_norm * second_norm))) if first_norm > 1e-12 and second_norm > 1e-12 else 0.0


class _ReservedVectorIndex:
    name = "reserved"
    def top_k(self, *args, **kwargs):
        raise NotImplementedError(f"{self.name} backend is reserved for a future release")


class FaissFeatureIndex(_ReservedVectorIndex): name = "faiss"
class QdrantFeatureIndex(_ReservedVectorIndex): name = "qdrant"
class MilvusFeatureIndex(_ReservedVectorIndex): name = "milvus"
