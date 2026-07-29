"""PostgreSQL-backed public write, audit, and distributed rate limiting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert

from autocamtracker.api.write_models import (
    AuditContext,
    RateLimitDecision,
    VehicleNotFound,
    VehiclePatchRequest,
    VehicleScopeDenied,
    VehicleWriteConflict,
    VehicleWriteResponse,
)
from autocamtracker.cloud.postgres_schema import api_rate_limits, audit_logs, vehicles


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


class PostgresVehicleWriteService:
    """Updates a vehicle and appends its audit record in one transaction."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def patch_vehicle(
        self,
        cloud_id: str,
        patch: VehiclePatchRequest,
        audit: AuditContext,
    ) -> VehicleWriteResponse:
        try:
            vehicle_id = UUID(cloud_id)
        except ValueError as error:
            raise VehicleNotFound(cloud_id) from error
        expected = _datetime(patch.expected_updated_at)
        audit_id = uuid4()
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            replay = connection.execute(
                select(audit_logs).where(
                    audit_logs.c.request_id == audit.request_id
                )
            ).mappings().first()
            if replay is not None:
                if (
                    replay["actor_uid"] != audit.actor.uid
                    or replay["action"] != "vehicle.patch"
                    or replay["resource_id"] != str(vehicle_id)
                ):
                    raise VehicleWriteConflict("Idempotency-Key was already used")
                return self._response(replay["after"], replay["audit_id"])
            before = connection.execute(
                select(vehicles)
                .where(vehicles.c.cloud_id == vehicle_id)
                .with_for_update()
            ).mappings().first()
            if before is None:
                raise VehicleNotFound(cloud_id)
            if not audit.actor.can_access_node(str(before["source_node_id"])):
                raise VehicleScopeDenied(str(before["source_node_id"]))
            actual_updated_at = before["updated_at"].astimezone(timezone.utc)
            if actual_updated_at != expected.astimezone(timezone.utc):
                raise VehicleWriteConflict(_iso(actual_updated_at))
            metadata = dict(before["metadata"] or {})
            if patch.metadata is not None:
                metadata.update(patch.metadata)
            values = {
                "display_name": patch.display_name or before["display_name"],
                "metadata": metadata,
                "updated_at": now,
            }
            after = connection.execute(
                update(vehicles)
                .where(
                    vehicles.c.cloud_id == vehicle_id,
                    vehicles.c.updated_at == before["updated_at"],
                )
                .values(**values)
                .returning(*vehicles.c)
            ).mappings().first()
            if after is None:
                raise VehicleWriteConflict(_iso(actual_updated_at))
            connection.execute(
                insert(audit_logs).values(
                    audit_id=audit_id,
                    request_id=audit.request_id,
                    actor_uid=audit.actor.uid,
                    actor_roles=sorted(audit.actor.roles),
                    action="vehicle.patch",
                    resource_type="vehicle",
                    resource_id=str(vehicle_id),
                    source_ip=audit.source_ip,
                    user_agent=audit.user_agent,
                    before=_json_value(dict(before)),
                    after=_json_value(dict(after)),
                    metadata={
                        "changed_fields": sorted(
                            name
                            for name, value in (
                                ("display_name", patch.display_name),
                                ("metadata", patch.metadata),
                            )
                            if value is not None
                        )
                    },
                )
            )
        return self._response(after, audit_id)

    @staticmethod
    def _response(row: Mapping[str, Any], audit_id: UUID) -> VehicleWriteResponse:
        updated_at = row["updated_at"]
        return VehicleWriteResponse(
            cloud_id=str(row["cloud_id"]),
            node_id=str(row["source_node_id"]),
            local_id=int(row["local_id"]),
            display_name=str(row["display_name"]),
            metadata=dict(row["metadata"] or {}),
            updated_at=(
                _iso(updated_at)
                if isinstance(updated_at, datetime)
                else str(updated_at)
            ),
            audit_id=str(audit_id),
        )


class PostgresRateLimiter:
    """Fixed-window limiter shared by every public API instance."""

    def __init__(self, engine: Engine, requests: int, window_seconds: int) -> None:
        self.engine = engine
        self.requests = max(1, int(requests))
        self.window_seconds = max(1, int(window_seconds))

    def consume(self, subject: str, route: str) -> RateLimitDecision:
        now = datetime.now(timezone.utc)
        epoch = int(now.timestamp())
        window_epoch = epoch - epoch % self.window_seconds
        window = datetime.fromtimestamp(window_epoch, tz=timezone.utc)
        with self.engine.begin() as connection:
            count = connection.scalar(
                insert(api_rate_limits)
                .values(
                    subject=subject,
                    route=route,
                    window_started_at=window,
                    request_count=1,
                )
                .on_conflict_do_update(
                    index_elements=[
                        api_rate_limits.c.subject,
                        api_rate_limits.c.route,
                        api_rate_limits.c.window_started_at,
                    ],
                    set_={"request_count": api_rate_limits.c.request_count + 1},
                )
                .returning(api_rate_limits.c.request_count)
            )
        if int(count) <= self.requests:
            return RateLimitDecision(True)
        retry_at = window + timedelta(seconds=self.window_seconds)
        return RateLimitDecision(
            False,
            max(1, int((retry_at - now).total_seconds()) + 1),
        )
