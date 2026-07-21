"""Enrollment limits and duplicate decisions for feature galleries."""

from __future__ import annotations

from autocamtracker.tracking.feature_models import CropQuality, GalleryType


class GalleryPolicy:
    def __init__(self, duplicate_threshold: float = 0.985, min_match_score: float = 0.72,
                 master_feature_limit: int = 500) -> None:
        self.duplicate_threshold = duplicate_threshold
        self.min_match_score = min_match_score
        self.master_feature_limit = master_feature_limit

    def rejection_reason(self, gallery_type: GalleryType, quality: CropQuality,
                         duplicate_score: float | None) -> str | None:
        if not quality.accepted:
            return quality.reason
        if gallery_type == "master" and duplicate_score is not None and duplicate_score >= self.duplicate_threshold:
            return f"duplicate master feature ({duplicate_score:.3f})"
        return None
