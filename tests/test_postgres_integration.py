from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.exc import DBAPIError

from autocamtracker.cloud.contracts import EventEnvelope, VehicleMutation
from autocamtracker.cloud.edge_outbox import EdgeOutbox, OutboxSynchronizer
from autocamtracker.cloud.importer import EdgeDataImporter
from autocamtracker.cloud.postgres import PostgresCloudAdapter
from autocamtracker.cloud.postgres_schema import events, vehicles
from autocamtracker.cloud.postgres_schema import audit_logs
from autocamtracker.cloud.security_store import (
    PostgresRateLimiter,
    PostgresVehicleWriteService,
)
from autocamtracker.api.auth import principal_from_claims
from autocamtracker.api.write_models import AuditContext, VehiclePatchRequest


DATABASE_URL = os.environ.get("AIVD_TEST_POSTGRES_URL")


@unittest.skipUnless(DATABASE_URL, "AIVD_TEST_POSTGRES_URL is not configured")
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", DATABASE_URL)
        command.upgrade(config, "head")
        cls.engine = create_engine(DATABASE_URL)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.node_id = f"integration-{uuid4()}"
        self.adapter = PostgresCloudAdapter(engine=self.engine)

    def test_adapter_is_idempotent_and_outbox_delivers_once(self) -> None:
        command_model = VehicleMutation(
            idempotency_key=str(uuid4()),
            node_id=self.node_id,
            local_id=1,
            display_name="Integration Car",
        )
        first = self.adapter.upsert_vehicle(command_model)
        second = self.adapter.upsert_vehicle(command_model)

        self.assertEqual(first.cloud_id, second.cloud_id)
        self.assertEqual(
            self.adapter.get_vehicle(node_id=self.node_id, local_id=1),
            first,
        )
        event = EventEnvelope(
            event_id=str(uuid4()),
            event_type="vehicle.updated",
            occurred_at=datetime.now(timezone.utc).isoformat(),
            source_node_id=self.node_id,
            schema_version=1,
            data={"local_id": 1},
        )
        with TemporaryDirectory() as directory:
            outbox = EdgeOutbox(Path(directory) / "outbox.sqlite3")
            try:
                outbox.enqueue(event)
                sync = OutboxSynchronizer(outbox, self.adapter)
                self.assertEqual(sync.run_once().delivered, 1)
                self.adapter.publish(event)
            finally:
                outbox.close()
        with self.engine.connect() as connection:
            count = connection.scalar(
                select(func.count()).select_from(events).where(
                    events.c.event_id == event.event_id
                )
            )
        self.assertEqual(count, 1)

    def test_sqlite_import_can_be_repeated_without_duplicates(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "identity.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    """
                    CREATE TABLE vehicles (
                        id INTEGER PRIMARY KEY, display_name TEXT, created_at REAL,
                        updated_at REAL, class_name TEXT, last_track_id INTEGER,
                        last_frame_index INTEGER, last_seen_timestamp REAL,
                        confidence REAL, bbox_json TEXT, center_json TEXT,
                        metadata_json TEXT
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO vehicles VALUES (1,'Imported',1,2,'car',NULL,3,2,0.8,'[]','[]','{}')"
                )
                connection.commit()
            importer = EdgeDataImporter(self.adapter, self.node_id)
            importer.import_sqlite(path)
            importer.import_sqlite(path)

        with self.engine.connect() as connection:
            count = connection.scalar(
                select(func.count()).select_from(vehicles).where(
                    vehicles.c.source_node_id == self.node_id
                )
            )
        self.assertEqual(count, 1)

    def test_patch_audit_is_atomic_idempotent_and_append_only(self) -> None:
        vehicle = self.adapter.upsert_vehicle(
            VehicleMutation(
                idempotency_key=str(uuid4()),
                node_id=self.node_id,
                local_id=2,
                display_name="Before",
            )
        )
        service = PostgresVehicleWriteService(self.engine)
        request_id = f"integration-{uuid4()}"
        audit = AuditContext(
            request_id=request_id,
            actor=principal_from_claims(
                {
                    "uid": "integration-user",
                    "roles": ["operator"],
                    "node_ids": [self.node_id],
                }
            ),
            source_ip="127.0.0.1",
            user_agent="integration-test",
        )
        patch = VehiclePatchRequest(
            expected_updated_at=vehicle.updated_at,
            display_name="After",
        )

        first = service.patch_vehicle(vehicle.cloud_id, patch, audit)
        replay = service.patch_vehicle(vehicle.cloud_id, patch, audit)

        self.assertEqual(first, replay)
        with self.engine.connect() as connection:
            count = connection.scalar(
                select(func.count()).select_from(audit_logs).where(
                    audit_logs.c.request_id == request_id
                )
            )
        self.assertEqual(count, 1)
        with self.assertRaises(DBAPIError):
            with self.engine.begin() as connection:
                connection.execute(
                    update(audit_logs)
                    .where(audit_logs.c.request_id == request_id)
                    .values(action="tampered")
                )

    def test_postgres_rate_limit_is_shared_state(self) -> None:
        route = f"test-route-{uuid4()}"
        limiter_a = PostgresRateLimiter(self.engine, requests=1, window_seconds=60)
        limiter_b = PostgresRateLimiter(self.engine, requests=1, window_seconds=60)

        self.assertTrue(limiter_a.consume(self.node_id, route).allowed)
        decision = limiter_b.consume(self.node_id, route)

        self.assertFalse(decision.allowed)
        self.assertGreaterEqual(decision.retry_after_seconds, 1)


if __name__ == "__main__":
    unittest.main()
