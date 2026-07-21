from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest

from autocamtracker.tracking.feature_models import CropQuality
from autocamtracker.tracking.feature_repository import FeatureRepository
from autocamtracker.tracking.sqlite_worker import SQLiteWorker
from autocamtracker.tracking.vehicle_identity_store import VehicleIdentityStore
from autocamtracker.vision.detector import TrackedDetection


def detection(frame_index: int, track_id: int | None = 1) -> TrackedDetection:
    return TrackedDetection(
        track_id=track_id,
        bbox=(10.0, 20.0, 90.0, 80.0),
        class_id=2,
        class_name="car",
        confidence=0.9,
        center=(50.0, 50.0),
        frame_index=frame_index,
        timestamp=float(frame_index),
        tracker_name="botsort",
    )


class SQLiteThreadingTests(unittest.TestCase):
    def test_worker_owns_connection_on_its_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            worker = SQLiteWorker(Path(temp_dir) / "worker.sqlite3", name="test-database")
            try:
                caller_ident = threading.get_ident()
                database_ident = worker.call(lambda connection: threading.get_ident())
                self.assertEqual(database_ident, worker.thread_ident)
                self.assertNotEqual(database_ident, caller_ident)
            finally:
                worker.close()

    def test_identity_updates_from_multiple_threads_are_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = VehicleIdentityStore(Path(temp_dir) / "identity.sqlite3", commit_interval_seconds=60.0)
            try:
                vehicle_id = store.create_vehicle(detection(1))
                with ThreadPoolExecutor(max_workers=4) as executor:
                    results = list(executor.map(
                        lambda frame_index: store.update_vehicle(vehicle_id, detection(frame_index)),
                        range(2, 42),
                    ))
                store.flush()
                stored = store.get_vehicle(vehicle_id)
                self.assertTrue(all(results))
                self.assertIsNotNone(stored)
                self.assertIn(stored.last_frame_index, range(2, 42))
            finally:
                store.close()

    def test_feature_writes_from_multiple_threads_are_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = FeatureRepository(Path(temp_dir) / "features.sqlite3")
            quality = CropQuality(True, 0.9, "ok", 80, 60, 100.0, 128.0)
            try:
                def insert(frame_index: int) -> int:
                    return repository.insert(
                        vehicle_id=1,
                        gallery_type="master",
                        detection=detection(frame_index),
                        quality=quality,
                        embedding=[1.0, float(frame_index)],
                        duplicate_score=None,
                        crop_jpeg=None,
                        model_path="test.onnx",
                    )

                with ThreadPoolExecutor(max_workers=4) as executor:
                    feature_ids = list(executor.map(insert, range(1, 21)))
                self.assertEqual(len(set(feature_ids)), 20)
                self.assertEqual(repository.summary_by_vehicle()[1]["master"], 20)
            finally:
                repository.close()

    def test_production_code_does_not_disable_sqlite_thread_checks(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "src" / "autocamtracker"
        offenders = []
        for path in source_root.rglob("*.py"):
            if "check_same_thread" in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(source_root)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
