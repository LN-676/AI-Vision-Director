from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from autocamtracker.cloud.importer import EdgeDataImporter, deterministic_cloud_id


class RecordingAdapter:
    def __init__(self) -> None:
        self.vehicles = []
        self.features = []
        self.rollbacks = []
        self.events = []

    def import_vehicle(self, node_id, row, cloud_id) -> None:
        self.vehicles.append((node_id, row, cloud_id))

    def import_feature(self, cloud_id, row) -> None:
        self.features.append((cloud_id, row))

    def import_rollback(self, node_id, row) -> None:
        self.rollbacks.append((node_id, row))

    def publish(self, event) -> None:
        self.events.append(event)


class EdgeDataImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.sqlite_path = self.root / "identity.sqlite3"
        self.adapter = RecordingAdapter()
        self.importer = EdgeDataImporter(self.adapter, "edge-1")  # type: ignore[arg-type]
        self._database()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _database(self) -> None:
        with closing(sqlite3.connect(self.sqlite_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE vehicles (
                    id INTEGER PRIMARY KEY, display_name TEXT, created_at REAL,
                    updated_at REAL, class_name TEXT, last_track_id INTEGER,
                    last_frame_index INTEGER, last_seen_timestamp REAL,
                    confidence REAL, bbox_json TEXT, center_json TEXT,
                    metadata_json TEXT
                );
                CREATE TABLE vehicle_features (
                    id INTEGER PRIMARY KEY, vehicle_id INTEGER, gallery_type TEXT,
                    created_at REAL, frame_index INTEGER, track_id INTEGER,
                    bbox_json TEXT, quality_score REAL, duplicate_score REAL,
                    embedding_json TEXT, crop_jpeg BLOB, metadata_json TEXT,
                    provenance_json TEXT, is_active INTEGER, rolled_back_at REAL,
                    rollback_reason TEXT
                );
                CREATE TABLE gallery_rollback_events (
                    id INTEGER PRIMARY KEY, created_at REAL, actor TEXT,
                    reason TEXT, feature_ids_json TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO vehicles VALUES (1,'Hero',1,2,'car',7,9,2,0.9,'[1,2,3,4]','[2,3]','{}')"
            )
            connection.execute(
                """
                INSERT INTO vehicle_features VALUES (
                    3,1,'master',2,9,7,'[1,2,3,4]',0.95,NULL,
                    '[0.1,0.2]',NULL,'{}','{"write_id":"w1"}',1,NULL,NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO gallery_rollback_events VALUES (4,3,'user','bad crop','[3]')"
            )
            connection.commit()

    def test_import_converts_all_sqlite_entities(self) -> None:
        report = self.importer.import_sqlite(self.sqlite_path)

        self.assertEqual(
            (report.vehicles, report.features, report.rollback_events),
            (1, 1, 1),
        )
        expected_id = deterministic_cloud_id("edge-1", 1)
        self.assertEqual(self.adapter.vehicles[0][2], expected_id)
        self.assertEqual(self.adapter.features[0][0], expected_id)
        self.assertEqual(self.adapter.features[0][1]["embedding"], [0.1, 0.2])
        self.assertEqual(self.adapter.rollbacks[0][1]["source_feature_ids"], [3])

    def test_telemetry_import_has_deterministic_event_ids(self) -> None:
        telemetry_dir = self.root / "telemetry"
        telemetry_dir.mkdir()
        path = telemetry_dir / "autocamtracker-telemetry-test.jsonl"
        payload = {
            "schema_version": 2,
            "session_id": "session-1",
            "event": "app_started",
            "severity": "info",
            "component": "desktop",
            "timestamp_ms": 1000,
        }
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

        self.assertEqual(self.importer.import_telemetry(telemetry_dir), 1)
        first_id = self.adapter.events[0].event_id
        self.adapter.events.clear()
        self.importer.import_telemetry(telemetry_dir)

        self.assertEqual(self.adapter.events[0].event_id, first_id)
        self.assertEqual(self.adapter.events[0].data["session_id"], "session-1")


if __name__ == "__main__":
    unittest.main()
