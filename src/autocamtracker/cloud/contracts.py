"""Ports shared by local adapters, cloud adapters, and delivery layers.

The interfaces in this module contain no HTTP, database, UI, or CV framework
types.  A web API, the current SQLite application, and future hosted workers can
therefore implement them independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Mapping, Protocol, TypeVar, runtime_checkable


EntityT = TypeVar("EntityT")
IdT = TypeVar("IdT")


def _required(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class Page(Generic[EntityT]):
    """A transport-neutral page with an opaque continuation cursor."""

    items: tuple[EntityT, ...] = ()
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            object.__setattr__(self, "items", tuple(self.items))
        if self.next_cursor is not None:
            _required("next_cursor", self.next_cursor)


@runtime_checkable
class Repository(Protocol[EntityT, IdT]):
    """Minimal persistence boundary; implementations own transaction details."""

    def get(self, entity_id: IdT) -> EntityT | None: ...

    def list(self, *, cursor: str | None = None, limit: int = 100) -> Page[EntityT]: ...

    def save(self, entity: EntityT) -> EntityT: ...

    def delete(self, entity_id: IdT) -> bool: ...


class SystemStatus(str, Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    OFFLINE = "offline"


@dataclass(frozen=True, slots=True)
class SystemStatusSnapshot:
    node_id: str
    status: SystemStatus
    observed_at: str
    version_label: str
    deployment_mode: str
    checks: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("node_id", "observed_at", "version_label", "deployment_mode"):
            _required(name, getattr(self, name))


@runtime_checkable
class SystemStatusQuery(Protocol):
    def get_system_status(self) -> SystemStatusSnapshot: ...


@dataclass(frozen=True, slots=True)
class VehicleRecord:
    """Cloud-safe vehicle metadata; feature vectors remain behind repositories."""

    node_id: str
    local_id: int
    cloud_id: str | None
    display_name: str
    created_at: str
    updated_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required("node_id", self.node_id)
        if self.local_id <= 0:
            raise ValueError("local_id must be positive")
        if self.cloud_id is not None:
            _required("cloud_id", self.cloud_id)
        for name in ("created_at", "updated_at"):
            _required(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class VehicleMutation:
    """Idempotent vehicle command addressed by a caller-generated key."""

    idempotency_key: str
    node_id: str
    local_id: int | None = None
    cloud_id: str | None = None
    display_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _required("idempotency_key", self.idempotency_key)
        _required("node_id", self.node_id)
        if self.local_id is not None and self.local_id <= 0:
            raise ValueError("local_id must be positive when present")
        if self.cloud_id is not None:
            _required("cloud_id", self.cloud_id)
        if self.local_id is None and self.cloud_id is None:
            raise ValueError("a local_id or cloud_id is required")


@runtime_checkable
class VehicleQuery(Protocol):
    def get_vehicle(
        self,
        *,
        node_id: str,
        local_id: int | None = None,
        cloud_id: str | None = None,
    ) -> VehicleRecord | None: ...

    def list_vehicles(
        self,
        *,
        node_id: str | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[VehicleRecord]: ...


@runtime_checkable
class VehicleCommand(Protocol):
    def upsert_vehicle(self, command: VehicleMutation) -> VehicleRecord: ...

    def delete_vehicle(self, command: VehicleMutation) -> bool: ...


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Versioned, replay-safe event passed to local or hosted event adapters."""

    event_id: str
    event_type: str
    occurred_at: str
    source_node_id: str
    schema_version: int
    data: Mapping[str, Any]
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "event_type", "occurred_at", "source_node_id"):
            _required(name, getattr(self, name))
        if self.schema_version <= 0:
            raise ValueError("schema_version must be positive")
        if self.correlation_id is not None:
            _required("correlation_id", self.correlation_id)


@runtime_checkable
class EventSink(Protocol):
    def publish(self, event: EventEnvelope) -> None: ...
