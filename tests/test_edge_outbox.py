from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from autocamtracker.cloud.contracts import EventEnvelope
from autocamtracker.cloud.edge_outbox import (
    CloudEventRouter,
    EdgeOutbox,
    OutboxSynchronizer,
)


class RecordingSink:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events = []

    def publish(self, event) -> None:
        if self.fail:
            raise RuntimeError("cloud unavailable")
        self.events.append(event)


class RecordingVehicleCommands:
    def __init__(self) -> None:
        self.upserts = []
        self.deletes = []

    def upsert_vehicle(self, command):
        self.upserts.append(command)

    def delete_vehicle(self, command):
        self.deletes.append(command)
        return True


class EdgeOutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.outbox = EdgeOutbox(
            Path(self.temporary_directory.name) / "edge-outbox.sqlite3"
        )

    def tearDown(self) -> None:
        self.outbox.close()
        self.temporary_directory.cleanup()

    def event(self, event_id: str | None = None) -> EventEnvelope:
        return EventEnvelope(
            event_id=event_id or str(uuid4()),
            event_type="vehicle.updated",
            occurred_at=datetime.now(timezone.utc).isoformat(),
            source_node_id="edge-1",
            schema_version=1,
            data={"local_id": 12},
        )

    def test_enqueue_is_durable_and_idempotent(self) -> None:
        event = self.event()

        self.assertTrue(self.outbox.enqueue(event))
        self.assertFalse(self.outbox.enqueue(event))
        self.assertEqual(self.outbox.counts()["pending"], 1)

    def test_synchronizer_delivers_and_acknowledges_batch(self) -> None:
        sink = RecordingSink()
        event = self.event()
        self.outbox.enqueue(event)

        result = OutboxSynchronizer(self.outbox, sink).run_once()

        self.assertEqual((result.claimed, result.delivered, result.failed), (1, 1, 0))
        self.assertEqual(sink.events, [event])
        self.assertEqual(self.outbox.counts()["delivered"], 1)

    def test_failure_returns_event_to_pending_with_error(self) -> None:
        event = self.event()
        self.outbox.enqueue(event)

        result = OutboxSynchronizer(self.outbox, RecordingSink(fail=True)).run_once()

        self.assertEqual(result.failed, 1)
        self.assertEqual(self.outbox.counts()["pending"], 1)

    def test_expired_lease_can_be_reclaimed(self) -> None:
        event = self.event()
        self.outbox.enqueue(event)
        first = self.outbox.claim(lease_seconds=30)
        self.assertEqual(first[0].attempts, 1)
        self.outbox._database.execute(
            "UPDATE outbox_events SET locked_until = 0 WHERE event_id = ?",
            (event.event_id,),
            commit=True,
        )

        second = self.outbox.claim()

        self.assertEqual(second[0].event, event)
        self.assertEqual(second[0].attempts, 2)

    def test_event_moves_to_dead_letter_after_max_attempts(self) -> None:
        event = self.event()
        self.outbox.enqueue(event)
        for _ in range(2):
            self.assertEqual(len(self.outbox.claim()), 1)
            self.outbox.mark_failed(
                event.event_id,
                "permanent failure",
                max_attempts=2,
                base_delay_seconds=0,
            )

        self.assertEqual(self.outbox.counts()["dead"], 1)
        self.assertEqual(self.outbox.claim(), [])

    def test_cloud_router_projects_vehicle_event_before_recording_it(self) -> None:
        commands = RecordingVehicleCommands()
        events = RecordingSink()
        event = EventEnvelope(
            event_id=str(uuid4()),
            event_type="vehicle.upsert",
            occurred_at=datetime.now(timezone.utc).isoformat(),
            source_node_id="edge-1",
            schema_version=1,
            data={
                "local_id": 12,
                "display_name": "Hero",
                "metadata": {"class_name": "car"},
            },
        )

        CloudEventRouter(commands, events).publish(event)

        self.assertEqual(commands.upserts[0].idempotency_key, event.event_id)
        self.assertEqual(commands.upserts[0].local_id, 12)
        self.assertEqual(events.events, [event])


if __name__ == "__main__":
    unittest.main()
