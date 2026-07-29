from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from autocamtracker.api import ApiSettings, create_app
from autocamtracker.api.read_models import ReadOnlyVehicleReader


class ReadOnlyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.db_path = self.root / "identity.sqlite3"
        self.telemetry_dir = self.root / "telemetry"
        self.telemetry_dir.mkdir()
        self._create_database()
        self._create_telemetry()
        self.client = TestClient(
            create_app(
                ApiSettings(
                    identity_db_path=self.db_path,
                    telemetry_dir=self.telemetry_dir,
                    node_id="test-node",
                )
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temporary_directory.cleanup()

    def _create_database(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                CREATE TABLE vehicles (
                    id INTEGER PRIMARY KEY,
                    display_name TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    class_name TEXT NOT NULL,
                    last_track_id INTEGER,
                    last_frame_index INTEGER NOT NULL,
                    last_seen_timestamp REAL NOT NULL,
                    confidence REAL NOT NULL,
                    bbox_json TEXT NOT NULL,
                    center_json TEXT NOT NULL,
                    metadata_json TEXT
                )
                """
            )
            connection.executemany(
                """
                INSERT INTO vehicles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        1,
                        "Hero Car",
                        1000.0,
                        1010.0,
                        "car",
                        7,
                        90,
                        1009.0,
                        0.9,
                        "[1,2,11,12]",
                        "[6,7]",
                        '{"color":"red"}',
                    ),
                    (
                        2,
                        None,
                        1001.0,
                        1020.0,
                        "truck",
                        None,
                        91,
                        1019.0,
                        0.8,
                        "[2,3,12,13]",
                        "[7,8]",
                        None,
                    ),
                ],
            )
            connection.commit()

    def _create_telemetry(self) -> None:
        records = [
            {
                "schema_version": 2,
                "session_id": "session-a",
                "event": "app_started",
                "severity": "info",
                "component": "desktop",
                "reason_code": None,
                "timestamp_ms": 1_000_000,
                "model": "yolo",
            },
            {
                "schema_version": 2,
                "session_id": "session-a",
                "event": "camera_failed",
                "severity": "error",
                "component": "camera_stream",
                "reason_code": "DECODE_FAILED",
                "timestamp_ms": 1_001_000,
            },
        ]
        path = self.telemetry_dir / "autocamtracker-telemetry-test.jsonl"
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def test_status_reports_local_read_only_mode(self) -> None:
        response = self.client.get("/api/v3/system/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")
        self.assertTrue(response.json()["read_only"])
        self.assertEqual(response.json()["checks"]["access_mode"], "read_only")

    def test_vehicle_list_get_and_cursor_pagination(self) -> None:
        first = self.client.get("/api/v3/vehicles", params={"limit": 1})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["items"][0]["local_id"], 2)
        self.assertEqual(first.json()["next_cursor"], "1")
        second = self.client.get(
            "/api/v3/vehicles",
            params={"limit": 1, "cursor": first.json()["next_cursor"]},
        )
        self.assertEqual(second.json()["items"][0]["display_name"], "Hero Car")
        self.assertIsNone(second.json()["next_cursor"])
        vehicle = self.client.get("/api/v3/vehicles/1")
        self.assertEqual(vehicle.json()["metadata"], {"color": "red"})
        self.assertIsNone(vehicle.json()["cloud_id"])

    def test_sessions_and_filtered_events_are_read_from_jsonl(self) -> None:
        sessions = self.client.get("/api/v3/sessions")

        self.assertEqual(sessions.status_code, 200)
        self.assertEqual(sessions.json()["items"][0]["session_id"], "session-a")
        self.assertEqual(sessions.json()["items"][0]["event_count"], 2)
        session = self.client.get("/api/v3/sessions/session-a")
        self.assertEqual(session.status_code, 200)
        events = self.client.get(
            "/api/v3/events",
            params={"session_id": "session-a", "minimum_severity": "warning"},
        )
        self.assertEqual(len(events.json()["items"]), 1)
        self.assertEqual(events.json()["items"][0]["reason_code"], "DECODE_FAILED")

    def test_openapi_exposes_only_get_operations_for_local_resources(self) -> None:
        response = self.client.get("/openapi.json")

        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertEqual(
            set(paths),
            {
                "/api/v3/system/status",
                "/api/v3/vehicles",
                "/api/v3/vehicles/{local_id}",
                "/api/v3/sessions",
                "/api/v3/sessions/{session_id}",
                "/api/v3/events",
            },
        )
        for operations in paths.values():
            self.assertEqual(set(operations), {"get"})

    def test_mutation_methods_are_not_registered(self) -> None:
        for method, path in (
            ("post", "/api/v3/vehicles"),
            ("put", "/api/v3/vehicles/1"),
            ("delete", "/api/v3/vehicles/1"),
            ("post", "/api/v3/events"),
        ):
            self.assertEqual(self.client.request(method, path).status_code, 405)

    def test_sqlite_connection_rejects_writes(self) -> None:
        reader = ReadOnlyVehicleReader(self.db_path, "test-node")

        with closing(reader._connect()) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM vehicles")

        with closing(sqlite3.connect(self.db_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
        self.assertEqual(count, 2)

    def test_invalid_cursor_and_missing_resources_have_stable_errors(self) -> None:
        self.assertEqual(
            self.client.get("/api/v3/vehicles", params={"cursor": "-1"}).status_code,
            422,
        )
        self.assertEqual(self.client.get("/api/v3/vehicles/999").status_code, 404)
        self.assertEqual(self.client.get("/api/v3/sessions/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
