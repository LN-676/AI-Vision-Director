"""Explicit, conflict-safe mapping between local SQLite and cloud vehicle IDs."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Protocol, runtime_checkable


def _required(name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True, slots=True)
class VehicleIdMapping:
    """One stable mapping scoped to the local node that created the vehicle."""

    node_id: str
    local_id: int
    cloud_id: str
    mapped_at: str

    def __post_init__(self) -> None:
        _required("node_id", self.node_id)
        if self.local_id <= 0:
            raise ValueError("local_id must be positive")
        _required("cloud_id", self.cloud_id)
        _required("mapped_at", self.mapped_at)


class VehicleIdMappingConflict(ValueError):
    """Raised when a local or cloud ID is already bound to another identity."""


@runtime_checkable
class VehicleIdMappingStore(Protocol):
    def bind(self, mapping: VehicleIdMapping) -> VehicleIdMapping: ...

    def by_local(self, node_id: str, local_id: int) -> VehicleIdMapping | None: ...

    def by_cloud(self, cloud_id: str) -> VehicleIdMapping | None: ...

    def unbind_local(self, node_id: str, local_id: int) -> bool: ...


class InMemoryVehicleIdMappingStore:
    """Reference adapter used by tests and single-process deployments.

    Production adapters can implement :class:`VehicleIdMappingStore` with
    SQLite or a hosted database while retaining identical conflict semantics.
    """

    def __init__(self) -> None:
        self._by_local: dict[tuple[str, int], VehicleIdMapping] = {}
        self._by_cloud: dict[str, VehicleIdMapping] = {}
        self._lock = RLock()

    def bind(self, mapping: VehicleIdMapping) -> VehicleIdMapping:
        local_key = (mapping.node_id, mapping.local_id)
        with self._lock:
            local_match = self._by_local.get(local_key)
            cloud_match = self._by_cloud.get(mapping.cloud_id)
            if local_match is not None and local_match.cloud_id != mapping.cloud_id:
                raise VehicleIdMappingConflict(
                    f"local vehicle {mapping.node_id}/{mapping.local_id} "
                    f"is already mapped to {local_match.cloud_id}"
                )
            if cloud_match is not None and (
                cloud_match.node_id != mapping.node_id
                or cloud_match.local_id != mapping.local_id
            ):
                raise VehicleIdMappingConflict(
                    f"cloud vehicle {mapping.cloud_id} is already mapped to "
                    f"{cloud_match.node_id}/{cloud_match.local_id}"
                )
            if local_match is not None:
                return local_match
            self._by_local[local_key] = mapping
            self._by_cloud[mapping.cloud_id] = mapping
            return mapping

    def by_local(self, node_id: str, local_id: int) -> VehicleIdMapping | None:
        with self._lock:
            return self._by_local.get((node_id, local_id))

    def by_cloud(self, cloud_id: str) -> VehicleIdMapping | None:
        with self._lock:
            return self._by_cloud.get(cloud_id)

    def unbind_local(self, node_id: str, local_id: int) -> bool:
        with self._lock:
            mapping = self._by_local.pop((node_id, local_id), None)
            if mapping is None:
                return False
            self._by_cloud.pop(mapping.cloud_id, None)
            return True
