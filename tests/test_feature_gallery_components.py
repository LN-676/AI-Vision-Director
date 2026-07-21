import tempfile
import unittest
from pathlib import Path

from autocamtracker.tracking.crop_quality_assessor import CropQualityAssessor
from autocamtracker.tracking.embedding_encoder import EmbeddingEncoder
from autocamtracker.tracking.feature_gallery import FeatureGallery
from autocamtracker.tracking.feature_models import CropQuality
from autocamtracker.tracking.feature_repository import FeatureRepository
from autocamtracker.tracking.gallery_policy import GalleryPolicy
from autocamtracker.tracking.identity_matcher import IdentityMatcher
from autocamtracker.tracking.vector_index import VectorIndex


class FeatureGalleryComponentTests(unittest.TestCase):
    def test_facade_composes_all_phase_six_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gallery = FeatureGallery(Path(temp_dir) / "features.sqlite3")
            try:
                self.assertIsInstance(gallery.crop_quality_assessor, CropQualityAssessor)
                self.assertIsInstance(gallery.embedding_encoder, EmbeddingEncoder)
                self.assertIsInstance(gallery.repository, FeatureRepository)
                self.assertIsInstance(gallery.vector_index, VectorIndex)
                self.assertIsInstance(gallery.gallery_policy, GalleryPolicy)
                self.assertIsInstance(gallery.identity_matcher, IdentityMatcher)
            finally:
                gallery.close()

    def test_gallery_policy_rejects_only_duplicate_master_features(self) -> None:
        policy = GalleryPolicy(duplicate_threshold=0.98)
        quality = CropQuality(True, 0.9, "ok", 100, 100, 90.0, 128.0)
        self.assertEqual(policy.rejection_reason("master", quality, 0.99), "duplicate master feature (0.990)")
        self.assertIsNone(policy.rejection_reason("candidate", quality, 0.99))

    def test_vector_index_cosine_similarity_is_bounded(self) -> None:
        self.assertEqual(VectorIndex.cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertEqual(VectorIndex.cosine_similarity([1.0, 0.0], [-1.0, 0.0]), 0.0)
        self.assertEqual(VectorIndex.cosine_similarity([1.0], [1.0, 0.0]), 0.0)

    def test_repository_reports_dominant_master_class(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = FeatureRepository(Path(temp_dir) / "features.sqlite3")
            try:
                for class_name in ("car", "truck", "car"):
                    repository.connection.execute(
                        """INSERT INTO vehicle_features
                        (vehicle_id, gallery_type, created_at, frame_index, bbox_json,
                         quality_score, embedding_json, metadata_json)
                        VALUES (1, 'master', 1.0, 1, '[]', 1.0, '[1.0]', ?)""",
                        (f'{{"class_name":"{class_name}"}}',),
                    )
                repository.connection.commit()
                self.assertEqual(repository.dominant_master_class(1), "car")
            finally:
                repository.close()


if __name__ == "__main__":
    unittest.main()
