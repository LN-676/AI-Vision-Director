import tempfile
import unittest
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from autocamtracker.tracking.auto_feature_sampler import AutoFeatureSampler
from autocamtracker.tracking.crop_quality_assessor import CropQualityAssessor
from autocamtracker.tracking.embedding_encoder import EmbeddingEncoder
from autocamtracker.tracking.feature_gallery import FeatureGallery
from autocamtracker.tracking.feature_models import (
    CropQuality,
    FeatureAddResult,
    GalleryWriteContext,
)
from autocamtracker.tracking.feature_repository import FeatureRepository
from autocamtracker.tracking.gallery_policy import GalleryPolicy
from autocamtracker.tracking.identity_matcher import IdentityMatcher
from autocamtracker.tracking.vector_index import VectorIndex
from autocamtracker.vision.detector import TrackedDetection


def detection(track_id: int | None = 7, frame_index: int = 3) -> TrackedDetection:
    return TrackedDetection(
        track_id=track_id,
        bbox=(10.0, 20.0, 90.0, 80.0),
        class_id=2,
        class_name="car",
        confidence=0.92,
        center=(50.0, 50.0),
        frame_index=frame_index,
        timestamp=float(frame_index),
        tracker_name="botsort",
    )


def context(**overrides) -> GalleryWriteContext:
    values = {
        "source": "test",
        "global_vehicle_id": 1,
        "local_track_id": 7,
        "identity_state": "LOCKED",
        "identity_reason_code": "CURRENT_TRACK_MATCH",
        "identity_score": 1.0,
        "identity_sub_scores": {"tracker_match": 1.0},
        "decision_accepted": True,
        "motor_safe_to_track": True,
    }
    values.update(overrides)
    return GalleryWriteContext(**values)


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
                         quality_score, embedding_json, metadata_json, provenance_json)
                        VALUES (1, 'master', 1.0, 1, '[]', 1.0, '[1.0]', ?, ?)""",
                        (
                            f'{{"class_name":"{class_name}"}}',
                            '{"write_id":"test-' + class_name + '","source":"test",'
                            '"global_vehicle_id":1,"frame_index":1,'
                            '"identity_state":"LOCKED","identity_score":1.0,'
                            '"identity_reason_code":"CURRENT_TRACK_MATCH","identity_sub_scores":{},'
                            '"decision_accepted":true,"motor_safe_to_track":true}',
                        ),
                    )
                repository.connection.commit()
                self.assertEqual(repository.dominant_master_class(1), "car")
            finally:
                repository.close()

    def test_gallery_write_gate_requires_high_confidence_locked_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gallery = FeatureGallery(Path(temp_dir) / "features.sqlite3")
            try:
                public_rejection = gallery.add_master_feature(1, detection(), None)
                self.assertFalse(public_rejection.accepted)
                self.assertIn("provenance is required", public_rejection.reason)
                self.assertIsNone(gallery._write_gate_reason(1, detection(), context()))
                self.assertIn(
                    "not LOCKED",
                    gallery._write_gate_reason(
                        1, detection(), context(identity_state="CONFIRMED")
                    ) or "",
                )
                self.assertIn(
                    "below 0.84",
                    gallery._write_gate_reason(
                        1, detection(), context(identity_score=0.83)
                    ) or "",
                )
                self.assertIn(
                    "destination GID",
                    gallery._write_gate_reason(
                        2, detection(), context()
                    ) or "",
                )
                self.assertIn(
                    "detection LID",
                    gallery._write_gate_reason(
                        1, detection(track_id=9), context()
                    ) or "",
                )
            finally:
                gallery.close()

    def test_embedding_provenance_is_saved_and_write_can_be_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gallery = FeatureGallery(Path(temp_dir) / "features.sqlite3")
            repository = gallery.repository
            quality = CropQuality(True, 0.9, "ok", 80, 60, 100.0, 128.0)
            provenance = {
                "write_id": "write-123",
                "source": "test",
                "global_vehicle_id": 1,
                "local_track_id": 7,
                "frame_index": 3,
                "identity_state": "LOCKED",
                "identity_reason_code": "CURRENT_TRACK_MATCH",
                "identity_score": 1.0,
                "identity_sub_scores": {"tracker_match": 1.0},
                "decision_accepted": True,
                "motor_safe_to_track": True,
            }
            try:
                feature_id = repository.insert(
                    1,
                    "master",
                    detection(),
                    quality,
                    [1.0, 0.0],
                    None,
                    None,
                    "test.onnx",
                    provenance,
                )

                snapshot = repository.snapshots(1)[0]
                self.assertEqual(snapshot.provenance["write_id"], "write-123")
                self.assertEqual(snapshot.provenance["identity_sub_scores"]["tracker_match"], 1.0)
                self.assertEqual(len(gallery.match_top_k([1.0, 0.0], vehicle_id=1)), 1)

                rollback = gallery.rollback_write(
                    "write-123", reason="suspected contamination", actor="test"
                )

                self.assertEqual(rollback.rolled_back_count, 1)
                self.assertEqual(rollback.feature_ids, (feature_id,))
                self.assertEqual(repository.summary_by_vehicle(), {})
                self.assertEqual(repository.stored_features("master"), [])
                self.assertEqual(gallery.match_top_k([1.0, 0.0], vehicle_id=1), [])
                audit_snapshot = repository.snapshots(
                    1, include_rolled_back=True
                )[0]
                self.assertFalse(audit_snapshot.active)
                self.assertEqual(audit_snapshot.rollback_reason, "suspected contamination")
                self.assertIsNotNone(rollback.event_id)
                event = repository.rollback_events()[0]
                self.assertEqual(event.event_id, rollback.event_id)
                self.assertEqual(event.feature_ids, (feature_id,))
                self.assertEqual(event.actor, "test")
            finally:
                gallery.close()

    def test_schema_migration_backfills_legacy_embedding_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("""CREATE TABLE vehicle_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_id INTEGER NOT NULL,
                gallery_type TEXT NOT NULL, created_at REAL NOT NULL,
                frame_index INTEGER NOT NULL, track_id INTEGER, bbox_json TEXT NOT NULL,
                quality_score REAL NOT NULL, duplicate_score REAL, embedding_json TEXT NOT NULL,
                crop_jpeg BLOB, metadata_json TEXT)""")
            connection.execute("""INSERT INTO vehicle_features
                (vehicle_id, gallery_type, created_at, frame_index, track_id, bbox_json,
                 quality_score, embedding_json, metadata_json)
                VALUES (5, 'master', 1.0, 9, 3, '[]', 0.8, '[1.0]', '{}')""")
            connection.commit()
            connection.close()

            repository = FeatureRepository(path)
            try:
                snapshot = repository.snapshots(5)[0]
                self.assertEqual(snapshot.provenance["source"], "legacy_migration")
                self.assertEqual(snapshot.provenance["write_id"], "legacy-1")
                self.assertEqual(snapshot.provenance["identity_state"], "UNKNOWN")
            finally:
                repository.close()

    def test_auto_sampler_forwards_current_identity_decision_as_provenance(self) -> None:
        class RecordingGallery:
            duplicate_threshold = 0.0

            def __init__(self) -> None:
                self.context = None

            def assess_crop_quality(self, frame, bbox):
                return CropQuality(True, 0.9, "ok", 80, 60, 100.0, 128.0)

            def has_master_features(self, vehicle_id):
                return False

            def add_master_feature(self, vehicle_id, candidate, frame, *, context=None):
                self.context = context
                quality = CropQuality(True, 0.9, "ok", 80, 60, 100.0, 128.0)
                return FeatureAddResult(True, vehicle_id, "master", 4, quality, reason="added")

        gallery = RecordingGallery()
        decision = SimpleNamespace(
            reason_code=SimpleNamespace(value="CURRENT_TRACK_MATCH"),
            score=1.0,
            sub_scores={"tracker_match": 1.0},
            accepted=True,
        )
        manager = SimpleNamespace(
            selected_global_vehicle_id=1,
            selected_local_track_id=7,
            identity_state=SimpleNamespace(value="LOCKED"),
            last_identity_decision=decision,
            motor_safe_to_track=True,
        )
        sampler = AutoFeatureSampler(gallery, identity_manager=manager)  # type: ignore[arg-type]
        frame = SimpleNamespace(shape=(200, 300, 3))

        result = sampler.start(1, detection(), frame, SimpleNamespace())  # type: ignore[arg-type]

        self.assertTrue(result.accepted)
        self.assertIsNotNone(gallery.context)
        self.assertEqual(gallery.context.identity_state, "LOCKED")
        self.assertEqual(gallery.context.identity_reason_code, "CURRENT_TRACK_MATCH")
        self.assertEqual(gallery.context.identity_sub_scores["tracker_match"], 1.0)


if __name__ == "__main__":
    unittest.main()
