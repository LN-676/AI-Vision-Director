"""PostgreSQL adapters for V3 cloud ports and bulk import."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import Engine, and_, create_engine, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from autocamtracker.cloud.contracts import (
    EventEnvelope,
    Page,
    VehicleMutation,
    VehicleRecord,
)
from autocamtracker.cloud.id_mapping import (
    VehicleIdMapping,
    VehicleIdMappingConflict,
)
from autocamtracker.cloud.postgres_schema import (
    events,
    gallery_rollback_events,
    idempotency_keys,
    nodes,
    sessions,
    vehicle_features,
    vehicle_id_mappings,
    vehicles,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _offset(cursor: str | None) -> int:
    try:
        value = 0 if cursor is None else int(cursor)
    except (TypeError, ValueError) as error:
        raise ValueError("cursor must be a non-negative integer") from error
    if value < 0:
        raise ValueError("cursor must be a non-negative integer")
    return value


class PostgresCloudAdapter:
    """Implements vehicle queries/commands, event sink, and ID mappings."""

    def __init__(self, database_url: str | None = None, *, engine: Engine | None = None) -> None:
        if engine is None and not database_url:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_engine(database_url, pool_pre_ping=True)

    def close(self) -> None:
        self.engine.dispose()

    def get_vehicle(
        self,
        *,
        node_id: str,
        local_id: int | None = None,
        cloud_id: str | None = None,
    ) -> VehicleRecord | None:
        if local_id is None and cloud_id is None:
            raise ValueError("local_id or cloud_id is required")
        conditions = [vehicles.c.source_node_id == node_id]
        if local_id is not None:
            conditions.append(vehicles.c.local_id == local_id)
        if cloud_id is not None:
            conditions.append(vehicles.c.cloud_id == _uuid(cloud_id))
        with self.engine.connect() as connection:
            row = connection.execute(select(vehicles).where(and_(*conditions))).mappings().first()
        return None if row is None else self._record(row)

    def list_vehicles(
        self,
        *,
        node_id: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[VehicleRecord]:
        requested = min(500, max(1, int(limit)))
        offset = _offset(cursor)
        statement = select(vehicles)
        if node_id is not None:
            statement = statement.where(vehicles.c.source_node_id == node_id)
        statement = statement.order_by(
            vehicles.c.updated_at.desc(),
            vehicles.c.cloud_id.desc(),
        ).limit(requested + 1).offset(offset)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return Page(
            tuple(self._record(row) for row in rows[:requested]),
            str(offset + requested) if len(rows) > requested else None,
        )

    def upsert_vehicle(self, command: VehicleMutation) -> VehicleRecord:
        if command.local_id is None:
            raise ValueError("local_id is required for an edge vehicle upsert")
        now = _utc_now()
        with self.engine.begin() as connection:
            replay = connection.execute(
                select(idempotency_keys).where(
                    idempotency_keys.c.idempotency_key == command.idempotency_key
                )
            ).mappings().first()
            if replay is not None:
                if replay["operation"] != "vehicle.upsert":
                    raise ValueError("idempotency key was used for another operation")
                row = connection.execute(
                    select(vehicles).where(
                        vehicles.c.cloud_id == _uuid(replay["resource_id"])
                    )
                ).mappings().one()
                return self._record(row)
            self._ensure_node(connection, command.node_id)
            cloud_id = _uuid(command.cloud_id) if command.cloud_id else uuid4()
            statement = insert(vehicles).values(
                cloud_id=cloud_id,
                source_node_id=command.node_id,
                local_id=command.local_id,
                display_name=command.display_name or str(command.local_id),
                class_name=str(command.metadata.get("class_name", "unknown")),
                last_seen_at=now,
                confidence=0.0,
                bbox=[],
                center=[],
                metadata=dict(command.metadata),
                created_at=now,
                updated_at=now,
            ).on_conflict_do_update(
                constraint="uq_vehicles_node_local",
                set_={
                    "display_name": command.display_name or vehicles.c.display_name,
                    "metadata": dict(command.metadata),
                    "updated_at": now,
                },
            ).returning(*vehicles.c)
            try:
                row = connection.execute(statement).mappings().one()
                if command.cloud_id is not None and row["cloud_id"] != cloud_id:
                    raise VehicleIdMappingConflict(
                        f"{command.node_id}/{command.local_id} is already mapped "
                        f"to {row['cloud_id']}"
                    )
                self._ensure_mapping(
                    connection,
                    command.node_id,
                    command.local_id,
                    row["cloud_id"],
                    now,
                )
                connection.execute(
                    insert(idempotency_keys).values(
                        idempotency_key=command.idempotency_key,
                        operation="vehicle.upsert",
                        resource_id=str(row["cloud_id"]),
                        response={},
                    )
                )
            except IntegrityError as error:
                raise VehicleIdMappingConflict(str(error.orig)) from error
        return self._record(row)

    def delete_vehicle(self, command: VehicleMutation) -> bool:
        with self.engine.begin() as connection:
            replay = connection.execute(
                select(idempotency_keys).where(
                    idempotency_keys.c.idempotency_key == command.idempotency_key
                )
            ).mappings().first()
            if replay is not None:
                if replay["operation"] != "vehicle.delete":
                    raise ValueError("idempotency key was used for another operation")
                return bool(replay["response"].get("deleted", False))
            conditions = [vehicles.c.source_node_id == command.node_id]
            if command.local_id is not None:
                conditions.append(vehicles.c.local_id == command.local_id)
            if command.cloud_id is not None:
                conditions.append(vehicles.c.cloud_id == _uuid(command.cloud_id))
            result = connection.execute(delete(vehicles).where(and_(*conditions)))
            deleted = result.rowcount > 0
            connection.execute(
                insert(idempotency_keys).values(
                    idempotency_key=command.idempotency_key,
                    operation="vehicle.delete",
                    response={"deleted": deleted},
                )
            )
            return deleted

    def publish(self, event: EventEnvelope) -> None:
        event_id = _uuid(event.event_id)
        data = dict(event.data)
        session_id = data.pop("session_id", None)
        with self.engine.begin() as connection:
            self._ensure_node(connection, event.source_node_id)
            if session_id:
                connection.execute(
                    insert(sessions)
                    .values(
                        session_id=str(session_id),
                        node_id=event.source_node_id,
                        started_at=_datetime(event.occurred_at),
                        event_count=0,
                        metadata={},
                    )
                    .on_conflict_do_nothing(index_elements=[sessions.c.session_id])
                )
            result = connection.execute(
                insert(events)
                .values(
                    event_id=event_id,
                    session_id=session_id,
                    source_node_id=event.source_node_id,
                    event_type=event.event_type,
                    occurred_at=_datetime(event.occurred_at),
                    severity=str(data.pop("severity", "info")),
                    component=str(data.pop("component", "application")),
                    reason_code=data.pop("reason_code", None),
                    schema_version=event.schema_version,
                    correlation_id=event.correlation_id,
                    data=data,
                )
                .on_conflict_do_nothing(index_elements=[events.c.event_id])
            )
            if session_id and result.rowcount > 0:
                connection.execute(
                    update(sessions)
                    .where(sessions.c.session_id == str(session_id))
                    .values(event_count=sessions.c.event_count + 1)
                )

    def bind(self, mapping: VehicleIdMapping) -> VehicleIdMapping:
        with self.engine.begin() as connection:
            vehicle = connection.execute(
                select(vehicles.c.cloud_id).where(
                    vehicles.c.source_node_id == mapping.node_id,
                    vehicles.c.local_id == mapping.local_id,
                    vehicles.c.cloud_id == _uuid(mapping.cloud_id),
                )
            ).first()
            if vehicle is None:
                raise VehicleIdMappingConflict("vehicle origin and cloud ID do not match")
            try:
                self._ensure_mapping(
                    connection,
                    mapping.node_id,
                    mapping.local_id,
                    _uuid(mapping.cloud_id),
                    _datetime(mapping.mapped_at),
                )
            except IntegrityError as error:
                raise VehicleIdMappingConflict(str(error.orig)) from error
        return mapping

    def by_local(self, node_id: str, local_id: int) -> VehicleIdMapping | None:
        return self._mapping(
            select(vehicle_id_mappings).where(
                vehicle_id_mappings.c.node_id == node_id,
                vehicle_id_mappings.c.local_id == local_id,
            )
        )

    def by_cloud(self, cloud_id: str) -> VehicleIdMapping | None:
        return self._mapping(
            select(vehicle_id_mappings).where(
                vehicle_id_mappings.c.cloud_id == _uuid(cloud_id)
            )
        )

    def unbind_local(self, node_id: str, local_id: int) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(vehicle_id_mappings).where(
                    vehicle_id_mappings.c.node_id == node_id,
                    vehicle_id_mappings.c.local_id == local_id,
                )
            )
            return result.rowcount > 0

    def import_vehicle(self, node_id: str, row: Mapping[str, Any], cloud_id: UUID) -> None:
        with self.engine.begin() as connection:
            self._ensure_node(connection, node_id)
            values = {
                "cloud_id": cloud_id,
                "source_node_id": node_id,
                "local_id": int(row["id"]),
                "display_name": str(row.get("display_name") or row["id"]),
                "class_name": str(row["class_name"]),
                "last_track_id": row.get("last_track_id"),
                "last_frame_index": int(row["last_frame_index"]),
                "last_seen_at": row["last_seen_at"],
                "confidence": float(row["confidence"]),
                "bbox": row["bbox"],
                "center": row["center"],
                "metadata": row["metadata"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            connection.execute(
                insert(vehicles).values(**values).on_conflict_do_update(
                    constraint="uq_vehicles_node_local",
                    set_={key: value for key, value in values.items() if key != "cloud_id"},
                )
            )
            self._ensure_mapping(
                connection,
                node_id,
                int(row["id"]),
                cloud_id,
                row["updated_at"],
            )

    def import_feature(self, cloud_id: UUID, row: Mapping[str, Any]) -> None:
        values = dict(row)
        values["vehicle_cloud_id"] = cloud_id
        with self.engine.begin() as connection:
            connection.execute(
                insert(vehicle_features).values(**values).on_conflict_do_update(
                    constraint="uq_vehicle_features_source",
                    set_={
                        key: value
                        for key, value in values.items()
                        if key not in {"vehicle_cloud_id", "source_feature_id"}
                    },
                )
            )

    def import_rollback(self, node_id: str, row: Mapping[str, Any]) -> None:
        values = dict(row)
        values["source_node_id"] = node_id
        with self.engine.begin() as connection:
            self._ensure_node(connection, node_id)
            connection.execute(
                insert(gallery_rollback_events)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_gallery_rollback_source")
            )

    def _mapping(self, statement) -> VehicleIdMapping | None:
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return VehicleIdMapping(
            node_id=row["node_id"],
            local_id=int(row["local_id"]),
            cloud_id=str(row["cloud_id"]),
            mapped_at=_iso(row["mapped_at"]),
        )

    @staticmethod
    def _record(row: Mapping[str, Any]) -> VehicleRecord:
        return VehicleRecord(
            node_id=str(row["source_node_id"]),
            local_id=int(row["local_id"]),
            cloud_id=str(row["cloud_id"]),
            display_name=str(row["display_name"]),
            created_at=_iso(row["created_at"]),
            updated_at=_iso(row["updated_at"]),
            metadata=dict(row["metadata"] or {}),
        )

    @staticmethod
    def _ensure_node(connection, node_id: str) -> None:
        connection.execute(
            insert(nodes)
            .values(node_id=node_id, last_seen_at=_utc_now(), metadata={})
            .on_conflict_do_update(
                index_elements=[nodes.c.node_id],
                set_={"last_seen_at": _utc_now()},
            )
        )

    @staticmethod
    def _ensure_mapping(connection, node_id, local_id, cloud_id, mapped_at) -> None:
        connection.execute(
            insert(vehicle_id_mappings)
            .values(
                node_id=node_id,
                local_id=local_id,
                cloud_id=cloud_id,
                mapped_at=mapped_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    vehicle_id_mappings.c.node_id,
                    vehicle_id_mappings.c.local_id,
                ]
            )
        )
