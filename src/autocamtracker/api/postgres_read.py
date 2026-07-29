"""PostgreSQL-backed read models for the hosted V3 API."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Engine, func, select, text

from autocamtracker.api.models import EventResponse, SessionResponse, VehicleResponse
from autocamtracker.cloud.postgres_schema import events, sessions, vehicles


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class PostgresReadStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def list_vehicles(self, *, offset: int, limit: int) -> tuple[list[VehicleResponse], bool]:
        statement = (
            select(vehicles)
            .order_by(vehicles.c.updated_at.desc(), vehicles.c.cloud_id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        items = [
            VehicleResponse(
                node_id=row["source_node_id"],
                local_id=row["local_id"],
                cloud_id=str(row["cloud_id"]),
                display_name=row["display_name"],
                class_name=row["class_name"],
                last_track_id=row["last_track_id"],
                last_frame_index=row["last_frame_index"],
                last_seen_at=_iso(row["last_seen_at"]),
                confidence=row["confidence"],
                bbox=tuple(row["bbox"]) if len(row["bbox"]) == 4 else (0, 0, 0, 0),
                center=tuple(row["center"]) if len(row["center"]) == 2 else (0, 0),
                created_at=_iso(row["created_at"]),
                updated_at=_iso(row["updated_at"]),
                metadata=row["metadata"],
            )
            for row in rows[:limit]
        ]
        return items, len(rows) > limit

    def list_sessions(self, *, offset: int, limit: int) -> tuple[list[SessionResponse], bool]:
        last_event = func.max(events.c.occurred_at).label("last_event_at")
        statement = (
            select(
                sessions.c.session_id,
                sessions.c.started_at,
                sessions.c.ended_at,
                sessions.c.event_count,
                sessions.c.source_file,
                last_event,
            )
            .outerjoin(events, events.c.session_id == sessions.c.session_id)
            .group_by(sessions.c.session_id)
            .order_by(sessions.c.started_at.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        items = [
            SessionResponse(
                session_id=row["session_id"],
                started_at=_iso(row["started_at"]),
                last_event_at=_iso(
                    row["last_event_at"] or row["ended_at"] or row["started_at"]
                ),
                event_count=row["event_count"],
                source_file=row["source_file"] or "",
            )
            for row in rows[:limit]
        ]
        return items, len(rows) > limit

    def list_events(
        self,
        *,
        offset: int,
        limit: int,
        session_id: str | None,
    ) -> tuple[list[EventResponse], bool]:
        statement = select(events)
        if session_id:
            statement = statement.where(events.c.session_id == session_id)
        statement = (
            statement.order_by(events.c.occurred_at.desc(), events.c.event_id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        items = [
            EventResponse(
                schema_version=row["schema_version"],
                session_id=row["session_id"] or "unscoped",
                event=row["event_type"],
                severity=row["severity"],
                component=row["component"],
                reason_code=row["reason_code"],
                timestamp_ms=int(row["occurred_at"].timestamp() * 1000),
                data=row["data"],
            )
            for row in rows[:limit]
        ]
        return items, len(rows) > limit
