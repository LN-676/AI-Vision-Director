"""ReID model lifecycle, batching, and short-lived track embedding cache."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from autocamtracker.tracking.crop_quality_assessor import CropQualityAssessor
from autocamtracker.tracking.reid_embedding import ReIDEmbeddingConfig, ReIDEmbeddingExtractor
from autocamtracker.vision.detector import TrackedDetection


@dataclass
class _CachedEmbedding:
    embedding: list[float]
    frame_index: int
    bbox: tuple[float, float, float, float]


class EmbeddingEncoder:
    def __init__(self, model_path: str, assessor: CropQualityAssessor) -> None:
        self.model_path = model_path
        self.assessor = assessor
        self.extractor: ReIDEmbeddingExtractor | None = None
        self._lock = Lock()
        self._cache: dict[int, _CachedEmbedding] = {}

    def reset_cache(self) -> None:
        self._cache.clear()

    def set_model(self, model_path: str) -> None:
        if model_path == self.model_path:
            return
        with self._lock:
            self.model_path, self.extractor = model_path, None
            self.reset_cache()

    def preload(self) -> bool:
        with self._lock:
            if self.extractor is None:
                self.extractor = ReIDEmbeddingExtractor(ReIDEmbeddingConfig(model_path=self.model_path))
            return self.extractor.available

    def encode(self, frame, detection: TrackedDetection, use_cache: bool = False) -> list[float] | None:
        cached = self._get_cached(detection) if use_cache else None
        if cached is not None:
            return cached
        with self._lock:
            if self.extractor is None:
                self.extractor = ReIDEmbeddingExtractor(ReIDEmbeddingConfig(model_path=self.model_path))
            embedding = self.extractor.extract(frame, self.assessor.feature_bbox(frame, detection.bbox))
        if embedding is not None and use_cache:
            self._store(detection, embedding)
        return embedding

    def encode_batch(self, frame, detections: list[TrackedDetection], use_cache: bool = False) -> list[list[float] | None]:
        results: list[list[float] | None] = [None] * len(detections)
        pending: list[int] = []
        bboxes = []
        for index, detection in enumerate(detections):
            cached = self._get_cached(detection) if use_cache else None
            if cached is not None:
                results[index] = cached
            else:
                pending.append(index)
                bboxes.append(self.assessor.feature_bbox(frame, detection.bbox))
        if pending:
            with self._lock:
                if self.extractor is None:
                    self.extractor = ReIDEmbeddingExtractor(ReIDEmbeddingConfig(model_path=self.model_path))
                embeddings = self.extractor.extract_batch(frame, bboxes)
            for index, embedding in zip(pending, embeddings or []):
                if embedding:
                    results[index] = embedding
                    if use_cache:
                        self._store(detections[index], embedding)
        self._trim_cache()
        return results

    def _get_cached(self, detection: TrackedDetection) -> list[float] | None:
        if detection.track_id is None:
            return None
        cached = self._cache.get(detection.track_id)
        if cached and 0 <= detection.frame_index - cached.frame_index <= 4 and self.bbox_iou(cached.bbox, detection.bbox) >= 0.5:
            return cached.embedding
        return None

    def _store(self, detection: TrackedDetection, embedding: list[float]) -> None:
        if detection.track_id is not None:
            self._cache[detection.track_id] = _CachedEmbedding(embedding, detection.frame_index, detection.bbox)
            self._trim_cache()

    def _trim_cache(self) -> None:
        for key in sorted(self._cache, key=lambda item: self._cache[item].frame_index)[:-256]:
            self._cache.pop(key, None)

    @staticmethod
    def bbox_iou(first, second) -> float:
        left, top = max(first[0], second[0]), max(first[1], second[1])
        right, bottom = min(first[2], second[2]), min(first[3], second[3])
        intersection = max(0.0, right - left) * max(0.0, bottom - top)
        first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
        second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
        union = first_area + second_area - intersection
        return intersection / union if union > 0.0 else 0.0
