"""Read-only adapters for local SQLite identity data and telemetry JSONL."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from autocamtracker.api.models import EventResponse, SessionResponse, VehicleResponse


def utc_iso_from_seconds(value: int | float) -> str:
    return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def encode_cursor(offset: int) -> str:
    return str(max(0, offset))


def decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except (TypeError, ValueError) as error:
        raise ValueError("cursor must be a non-negative integer") from error
    if value < 0:
        raise ValueError("cursor must be a non-negative integer")
    return value


class ReadOnlyVehicleReader:
    """Queries vehicle snapshots without sharing the desktop write connection."""

    def __init__(self, db_path: Path, node_id: str) -> None:
        self.db_path = Path(db_path)
        self.node_id = node_id

    def available(self) -> bool:
        try:
            with closing(self._connect()) as connection:
                connection.execute("SELECT 1 FROM vehicles LIMIT 1").fetchone()
            return True
        except (OSError, sqlite3.Error):
            return False

    def get(self, local_id: int) -> VehicleResponse | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"{self._select_sql()} WHERE id = ?",
                (local_id,),
            ).fetchone()
        return None if row is None else self._vehicle(row)

    def list(self, *, offset: int, limit: int) -> tuple[list[VehicleResponse], bool]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"{self._select_sql()} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
                (limit + 1, offset),
            ).fetchall()
        return [self._vehicle(row) for row in rows[:limit]], len(rows) > limit

    def _connect(self) -> sqlite3.Connection:
        if not self.db_path.is_file():
            raise FileNotFoundError(self.db_path)
        connection = sqlite3.connect(
            self.db_path.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=1.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 1000")
        return connection

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT id, display_name, created_at, updated_at, class_name,
                   last_track_id, last_frame_index, last_seen_timestamp,
                   confidence, bbox_json, center_json, metadata_json
            FROM vehicles
        """

    def _vehicle(self, row: sqlite3.Row) -> VehicleResponse:
        local_id = int(row["id"])
        return VehicleResponse(
            node_id=self.node_id,
            local_id=local_id,
            cloud_id=None,
            display_name=str(row["display_name"]).strip() if row["display_name"] else str(local_id),
            class_name=str(row["class_name"]),
            last_track_id=int(row["last_track_id"]) if row["last_track_id"] is not None else None,
            last_frame_index=max(0, int(row["last_frame_index"])),
            last_seen_at=utc_iso_from_seconds(row["last_seen_timestamp"]),
            confidence=float(row["confidence"]),
            bbox=self._tuple(row["bbox_json"], 4),
            center=self._tuple(row["center_json"], 2),
            created_at=utc_iso_from_seconds(row["created_at"]),
            updated_at=utc_iso_from_seconds(row["updated_at"]),
            metadata=self._object(row["metadata_json"]),
        )

    @staticmethod
    def _tuple(value: str, length: int) -> tuple:
        parsed = json.loads(value)
        if not isinstance(parsed, list) or len(parsed) != length:
            raise ValueError("invalid coordinate data in vehicle database")
        return tuple(float(item) for item in parsed)

    @staticmethod
    def _object(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


class TelemetryReader:
    """Builds session and event read models from immutable JSONL snapshots."""

    def __init__(self, telemetry_dir: Path) -> None:
        self.telemetry_dir = Path(telemetry_dir)

    def available(self) -> bool:
        return self.telemetry_dir.is_dir()

    def list_sessions(self, *, offset: int, limit: int) -> tuple[list[SessionResponse], bool]:
        sessions = sorted(
            (summary for path in self._paths() if (summary := self._session(path)) is not None),
            key=lambda item: item.last_event_at,
            reverse=True,
        )
        page = sessions[offset:offset + limit + 1]
        return page[:limit], len(page) > limit

    def get_session(self, session_id: str) -> SessionResponse | None:
        return next(
            (
                summary
                for path in self._paths()
                if (summary := self._session(path)) is not None
                and summary.session_id == session_id
            ),
            None,
        )

    def list_events(
        self,
        *,
        offset: int,
        limit: int,
        session_id: str | None = None,
        minimum_severity: str | None = None,
    ) -> tuple[list[EventResponse], bool]:
        ranks = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}
        threshold = ranks.get((minimum_severity or "debug").lower())
        if threshold is None:
            raise ValueError("unsupported minimum_severity")
        events = []
        for path in self._paths():
            for payload in self._records(path):
                if session_id is not None and payload.get("session_id") != session_id:
                    continue
                severity = str(payload.get("severity", "info")).lower()
                if ranks.get(severity, 20) < threshold:
                    continue
                events.append(self._event(payload))
        events.sort(key=lambda item: item.timestamp_ms, reverse=True)
        page = events[offset:offset + limit + 1]
        return page[:limit], len(page) > limit

    def _paths(self) -> list[Path]:
        if not self.telemetry_dir.is_dir():
            return []
        return sorted(self.telemetry_dir.glob("autocamtracker-telemetry-*.jsonl"))

    def _session(self, path: Path) -> SessionResponse | None:
        session_id = None
        first_timestamp = None
        last_timestamp = None
        event_count = 0
        for payload in self._records(path):
            timestamp = self._timestamp(payload)
            session_id = session_id or str(payload.get("session_id") or path.stem)
            first_timestamp = timestamp if first_timestamp is None else min(first_timestamp, timestamp)
            last_timestamp = timestamp if last_timestamp is None else max(last_timestamp, timestamp)
            event_count += 1
        if event_count == 0 or first_timestamp is None or last_timestamp is None:
            return None
        return SessionResponse(
            session_id=session_id or path.stem,
            started_at=utc_iso_from_seconds(first_timestamp / 1000),
            last_event_at=utc_iso_from_seconds(last_timestamp / 1000),
            event_count=event_count,
            source_file=path.name,
        )

    def _records(self, path: Path) -> Iterator[dict[str, Any]]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        payload = json.loads(line)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    if isinstance(payload, dict):
                        yield payload
        except OSError:
            return

    def _event(self, payload: dict[str, Any]) -> EventResponse:
        known = {
            "schema_version",
            "session_id",
            "event",
            "severity",
            "component",
            "reason_code",
            "timestamp_ms",
        }
        return EventResponse(
            schema_version=max(1, int(payload.get("schema_version", 1))),
            session_id=str(payload.get("session_id", "unknown")),
            event=str(payload.get("event", "unknown")),
            severity=str(payload.get("severity", "info")).lower(),
            component=str(payload.get("component", "application")),
            reason_code=str(payload["reason_code"]) if payload.get("reason_code") else None,
            timestamp_ms=self._timestamp(payload),
            data={key: value for key, value in payload.items() if key not in known},
        )

    @staticmethod
    def _timestamp(payload: dict[str, Any]) -> int:
        try:
            return max(0, int(payload.get("timestamp_ms", 0)))
        except (TypeError, ValueError):
            return 0
