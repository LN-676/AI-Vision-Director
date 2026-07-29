"""Cloud-neutral boundaries for the deployable V3 application."""

from autocamtracker.cloud.contracts import (
    EventEnvelope,
    EventSink,
    Page,
    Repository,
    SystemStatus,
    SystemStatusQuery,
    SystemStatusSnapshot,
    VehicleCommand,
    VehicleMutation,
    VehicleQuery,
    VehicleRecord,
)
from autocamtracker.cloud.id_mapping import (
    InMemoryVehicleIdMappingStore,
    VehicleIdMapping,
    VehicleIdMappingConflict,
    VehicleIdMappingStore,
)

__all__ = [
    "EventEnvelope",
    "EventSink",
    "InMemoryVehicleIdMappingStore",
    "Page",
    "Repository",
    "SystemStatus",
    "SystemStatusQuery",
    "SystemStatusSnapshot",
    "VehicleCommand",
    "VehicleIdMapping",
    "VehicleIdMappingConflict",
    "VehicleIdMappingStore",
    "VehicleMutation",
    "VehicleQuery",
    "VehicleRecord",
]
