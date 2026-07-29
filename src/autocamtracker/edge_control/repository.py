"""Repository port and SQLite adapter for Edge commands and heartbeat state."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Protocol
from uuid import UUID

from autocamtracker.edge_control.models import (
    CommandAck,
    CommandCreate,
    CommandStatus,
    EdgeCommand,
    EdgeNodeState,
    Heartbeat,
)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class EdgeControlRepository(Protocol):
    def create_command(self, node_id: str, command: CommandCreate) -> EdgeCommand: ...
    def claim_command(self, node_id: str, lease_seconds: int) -> EdgeCommand | None: ...
    def ack_command(self, command_id: UUID, node_id: str, ack: CommandAck) -> EdgeCommand | None: ...
    def heartbeat(self, node_id: str, heartbeat: Heartbeat) -> EdgeNodeState: ...
    def list_nodes(self, offline_after_seconds: int) -> list[EdgeNodeState]: ...
    def get_node(self, node_id: str, offline_after_seconds: int) -> EdgeNodeState | None: ...


class SQLiteEdgeControlRepository:
    """Short-lived SQLite connections keep the adapter thread-safe."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS edge_nodes (
                    node_id TEXT PRIMARY KEY,
                    heartbeat_json TEXT NOT NULL,
                    last_heartbeat TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS edge_commands (
                    command_id TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    actor_uid TEXT NOT NULL,
                    command_type TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    claimed_at TEXT,
                    lease_expires_at TEXT,
                    completed_at TEXT,
                    result_json TEXT,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_edge_claim
                ON edge_commands(node_id, status, priority DESC, created_at ASC);
                """
            )
            connection.commit()

    def create_command(self, node_id: str, command: CommandCreate) -> EdgeCommand:
        now = datetime.now(timezone.utc)
        priority = 1000 if command.command_type.value == "emergency_stop" else 100
        status = (
            CommandStatus.EXPIRED
            if command.expires_at <= now
            else CommandStatus.QUEUED
        )
        completed_at = now if status == CommandStatus.EXPIRED else None
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO edge_commands (
                    command_id,node_id,actor_uid,command_type,parameters_json,
                    priority,status,created_at,expires_at,completed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(command.command_id),
                    node_id,
                    command.actor_uid,
                    command.command_type.value,
                    json.dumps(command.parameters, separators=(",", ":")),
                    priority,
                    status.value,
                    _iso(now),
                    _iso(command.expires_at),
                    _iso(completed_at) if completed_at else None,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM edge_commands WHERE command_id=?",
                (str(command.command_id),),
            ).fetchone()
        return self._command(row)

    def claim_command(self, node_id: str, lease_seconds: int) -> EdgeCommand | None:
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=lease_seconds)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE edge_commands
                SET status='expired', completed_at=?
                WHERE node_id=? AND status IN ('queued','claimed','executing')
                  AND expires_at <= ?
                """,
                (_iso(now), node_id, _iso(now)),
            )
            row = connection.execute(
                """
                SELECT * FROM edge_commands
                WHERE node_id=? AND expires_at > ? AND (
                    status='queued'
                    OR (status IN ('claimed','executing') AND lease_expires_at <= ?)
                )
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                """,
                (node_id, _iso(now), _iso(now)),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE edge_commands
                SET status='claimed', claimed_at=?, lease_expires_at=?
                WHERE command_id=?
                """,
                (_iso(now), _iso(lease_until), row["command_id"]),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM edge_commands WHERE command_id=?",
                (row["command_id"],),
            ).fetchone()
        return self._command(row)

    def ack_command(
        self, command_id: UUID, node_id: str, ack: CommandAck
    ) -> EdgeCommand | None:
        now = datetime.now(timezone.utc)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM edge_commands WHERE command_id=? AND node_id=?",
                (str(command_id), node_id),
            ).fetchone()
            if row is None:
                return None
            current = CommandStatus(row["status"])
            if current in {
                CommandStatus.SUCCEEDED,
                CommandStatus.FAILED,
                CommandStatus.EXPIRED,
            }:
                return self._command(row)
            if datetime.fromisoformat(row["expires_at"]) <= now:
                connection.execute(
                    "UPDATE edge_commands SET status='expired', completed_at=? WHERE command_id=?",
                    (_iso(now), str(command_id)),
                )
            else:
                completed = (
                    now
                    if ack.status in {CommandStatus.SUCCEEDED, CommandStatus.FAILED}
                    else None
                )
                connection.execute(
                    """
                    UPDATE edge_commands
                    SET status=?, completed_at=?, result_json=?, error_message=?
                    WHERE command_id=?
                    """,
                    (
                        ack.status.value,
                        _iso(completed) if completed else None,
                        json.dumps(ack.result, separators=(",", ":"))
                        if ack.result is not None
                        else None,
                        ack.error_message,
                        str(command_id),
                    ),
                )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM edge_commands WHERE command_id=?",
                (str(command_id),),
            ).fetchone()
        return self._command(row)

    def heartbeat(self, node_id: str, heartbeat: Heartbeat) -> EdgeNodeState:
        now = datetime.now(timezone.utc)
        payload = heartbeat.model_dump(mode="json")
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO edge_nodes(node_id, heartbeat_json, last_heartbeat)
                VALUES (?,?,?)
                ON CONFLICT(node_id) DO UPDATE SET
                    heartbeat_json=excluded.heartbeat_json,
                    last_heartbeat=excluded.last_heartbeat
                """,
                (node_id, json.dumps(payload, separators=(",", ":")), _iso(now)),
            )
            connection.commit()
        return self.get_node(node_id, 10)  # type: ignore[return-value]

    def list_nodes(self, offline_after_seconds: int) -> list[EdgeNodeState]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM edge_nodes ORDER BY last_heartbeat DESC"
            ).fetchall()
        return [self._node(row, offline_after_seconds) for row in rows]

    def get_node(
        self, node_id: str, offline_after_seconds: int
    ) -> EdgeNodeState | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM edge_nodes WHERE node_id=?", (node_id,)
            ).fetchone()
            commands = connection.execute(
                """
                SELECT * FROM edge_commands WHERE node_id=?
                ORDER BY created_at DESC LIMIT 10
                """,
                (node_id,),
            ).fetchall()
        if row is None:
            return None
        node = self._node(row, offline_after_seconds)
        return node.model_copy(
            update={"recent_commands": [self._command(item) for item in commands]}
        )

    def _node(self, row: sqlite3.Row, offline_after_seconds: int) -> EdgeNodeState:
        heartbeat = json.loads(row["heartbeat_json"])
        last = datetime.fromisoformat(row["last_heartbeat"])
        online = (
            bool(heartbeat.get("online", True))
            and (datetime.now(timezone.utc) - last).total_seconds()
            <= offline_after_seconds
        )
        return EdgeNodeState(
            node_id=row["node_id"],
            last_heartbeat=last,
            online=online,
            recent_commands=[],
            **{key: value for key, value in heartbeat.items() if key != "online"},
        )

    @staticmethod
    def _command(row: sqlite3.Row) -> EdgeCommand:
        return EdgeCommand(
            command_id=UUID(row["command_id"]),
            node_id=row["node_id"],
            actor_uid=row["actor_uid"],
            command_type=row["command_type"],
            parameters=json.loads(row["parameters_json"]),
            priority=row["priority"],
            status=row["status"],
            created_at=_dt(row["created_at"]),
            expires_at=_dt(row["expires_at"]),
            claimed_at=_dt(row["claimed_at"]),
            lease_expires_at=_dt(row["lease_expires_at"]),
            completed_at=_dt(row["completed_at"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error_message=row["error_message"],
        )
