"""Durable SQLite outbox and idempotent PostgreSQL synchronization."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from time import sleep, time

from autocamtracker.cloud.contracts import (
    EventEnvelope,
    EventSink,
    VehicleCommand,
    VehicleMutation,
)
from autocamtracker.tracking.sqlite_worker import SQLiteWorker


@dataclass(frozen=True, slots=True)
class OutboxItem:
    event: EventEnvelope
    attempts: int


@dataclass(frozen=True, slots=True)
class SyncResult:
    claimed: int
    delivered: int
    failed: int


class EdgeOutbox(EventSink):
    """Single-owner local outbox with leases, retries, and a dead-letter state."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._database = SQLiteWorker(self.db_path, name="edge-outbox")
        self._ensure_schema()

    def close(self) -> None:
        self._database.close()

    def publish(self, event: EventEnvelope) -> None:
        self.enqueue(event)

    def enqueue(self, event: EventEnvelope) -> bool:
        cursor = self._database.execute(
            """
            INSERT OR IGNORE INTO outbox_events (
                event_id, event_type, payload_json, created_at, available_at,
                attempts, status
            ) VALUES (?, ?, ?, ?, ?, 0, 'pending')
            """,
            (
                event.event_id,
                event.event_type,
                json.dumps(asdict(event), sort_keys=True, separators=(",", ":")),
                time(),
                time(),
            ),
            commit=True,
        )
        return cursor.rowcount > 0

    def claim(self, *, limit: int = 100, lease_seconds: float = 30.0) -> list[OutboxItem]:
        requested = min(500, max(1, int(limit)))
        now = time()

        def operation(connection) -> list[OutboxItem]:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE outbox_events
                SET status = 'pending', locked_until = NULL
                WHERE status = 'inflight' AND locked_until < ?
                """,
                (now,),
            )
            rows = connection.execute(
                """
                SELECT event_id, payload_json, attempts
                FROM outbox_events
                WHERE status = 'pending' AND available_at <= ?
                ORDER BY created_at, event_id
                LIMIT ?
                """,
                (now, requested),
            ).fetchall()
            ids = [str(row["event_id"]) for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"""
                    UPDATE outbox_events
                    SET status = 'inflight', locked_until = ?, attempts = attempts + 1
                    WHERE event_id IN ({placeholders})
                    """,
                    (now + max(1.0, lease_seconds), *ids),
                )
            connection.commit()
            return [
                OutboxItem(
                    event=EventEnvelope(**json.loads(row["payload_json"])),
                    attempts=int(row["attempts"]) + 1,
                )
                for row in rows
            ]

        return self._database.call(operation)

    def mark_delivered(self, event_id: str) -> bool:
        cursor = self._database.execute(
            """
            UPDATE outbox_events
            SET status = 'delivered', delivered_at = ?, locked_until = NULL,
                last_error = NULL
            WHERE event_id = ? AND status = 'inflight'
            """,
            (time(), event_id),
            commit=True,
        )
        return cursor.rowcount > 0

    def mark_failed(
        self,
        event_id: str,
        error: str,
        *,
        max_attempts: int = 10,
        base_delay_seconds: float = 1.0,
    ) -> bool:
        row = self._database.execute(
            "SELECT attempts FROM outbox_events WHERE event_id = ? AND status = 'inflight'",
            (event_id,),
        ).fetchone()
        if row is None:
            return False
        attempts = int(row["attempts"])
        dead = attempts >= max(1, int(max_attempts))
        delay = min(300.0, max(0.0, base_delay_seconds) * (2 ** max(0, attempts - 1)))
        cursor = self._database.execute(
            """
            UPDATE outbox_events
            SET status = ?, available_at = ?, locked_until = NULL, last_error = ?
            WHERE event_id = ? AND status = 'inflight'
            """,
            (
                "dead" if dead else "pending",
                time() + delay,
                str(error)[:2000],
                event_id,
            ),
            commit=True,
        )
        return cursor.rowcount > 0

    def counts(self) -> dict[str, int]:
        rows = self._database.execute(
            "SELECT status, COUNT(*) AS count FROM outbox_events GROUP BY status"
        ).fetchall()
        counts = {"pending": 0, "inflight": 0, "delivered": 0, "dead": 0}
        counts.update({str(row["status"]): int(row["count"]) for row in rows})
        return counts

    def _ensure_schema(self) -> None:
        self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS outbox_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                available_at REAL NOT NULL,
                locked_until REAL,
                delivered_at REAL,
                attempts INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','inflight','delivered','dead')),
                last_error TEXT
            )
            """,
            commit=True,
        )
        self._database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_outbox_ready
            ON outbox_events(status, available_at, created_at)
            """,
            commit=True,
        )


class OutboxSynchronizer:
    def __init__(
        self,
        outbox: EdgeOutbox,
        remote_sink: EventSink,
        *,
        batch_size: int = 100,
        lease_seconds: float = 30.0,
        max_attempts: int = 10,
    ) -> None:
        self.outbox = outbox
        self.remote_sink = remote_sink
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def run_once(self) -> SyncResult:
        items = self.outbox.claim(
            limit=self.batch_size,
            lease_seconds=self.lease_seconds,
        )
        delivered = 0
        failed = 0
        for item in items:
            try:
                self.remote_sink.publish(item.event)
            except Exception as error:
                self.outbox.mark_failed(
                    item.event.event_id,
                    str(error),
                    max_attempts=self.max_attempts,
                )
                failed += 1
            else:
                self.outbox.mark_delivered(item.event.event_id)
                delivered += 1
        return SyncResult(len(items), delivered, failed)


class CloudEventRouter:
    """Applies vehicle events idempotently, then records the source event."""

    def __init__(self, vehicle_commands: VehicleCommand, events: EventSink) -> None:
        self.vehicle_commands = vehicle_commands
        self.events = events

    def publish(self, event: EventEnvelope) -> None:
        if event.event_type in {"vehicle.upsert", "vehicle.delete"}:
            local_id = event.data.get("local_id")
            cloud_id = event.data.get("cloud_id")
            command = VehicleMutation(
                idempotency_key=event.event_id,
                node_id=event.source_node_id,
                local_id=int(local_id) if local_id is not None else None,
                cloud_id=str(cloud_id) if cloud_id is not None else None,
                display_name=(
                    str(event.data["display_name"])
                    if event.data.get("display_name") is not None
                    else None
                ),
                metadata=(
                    dict(event.data["metadata"])
                    if isinstance(event.data.get("metadata"), dict)
                    else {}
                ),
            )
            if event.event_type == "vehicle.upsert":
                self.vehicle_commands.upsert_vehicle(command)
            else:
                self.vehicle_commands.delete_vehicle(command)
        self.events.publish(event)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the edge outbox to PostgreSQL")
    parser.add_argument("--outbox", type=Path, default=Path("outputs/edge_outbox.sqlite3"))
    parser.add_argument("--database-url", default=os.environ.get("AIVD_DATABASE_URL"))
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or AIVD_DATABASE_URL is required")

    from autocamtracker.cloud.postgres import PostgresCloudAdapter

    outbox = EdgeOutbox(args.outbox)
    remote = PostgresCloudAdapter(args.database_url)
    synchronizer = OutboxSynchronizer(
        outbox,
        CloudEventRouter(remote, remote),
        batch_size=args.batch_size,
    )
    try:
        while True:
            result = synchronizer.run_once()
            print(json.dumps(asdict(result), separators=(",", ":")))
            if not args.watch:
                break
            sleep(max(0.1, args.interval))
    finally:
        remote.close()
        outbox.close()
