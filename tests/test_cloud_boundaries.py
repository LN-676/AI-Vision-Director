import json
from pathlib import Path
import unittest

from autocamtracker.cloud import (
    EventEnvelope,
    EventSink,
    InMemoryVehicleIdMappingStore,
    Repository,
    SystemStatusQuery,
    VehicleCommand,
    VehicleIdMapping,
    VehicleIdMappingConflict,
    VehicleQuery,
)
from autocamtracker.product import RELEASE_LABEL


class CloudBoundaryTests(unittest.TestCase):
    def mapping(self, **overrides) -> VehicleIdMapping:
        values = {
            "node_id": "mac-studio-1",
            "local_id": 12,
            "cloud_id": "veh_01K0ABC",
            "mapped_at": "2026-07-29T10:00:00Z",
        }
        values.update(overrides)
        return VehicleIdMapping(**values)

    def test_release_label_is_exact(self) -> None:
        self.assertEqual(RELEASE_LABEL, "AI-Vision-Director V3.0.0a1")

    def test_boundary_types_are_runtime_protocols(self) -> None:
        for boundary in (
            Repository,
            SystemStatusQuery,
            VehicleQuery,
            VehicleCommand,
            EventSink,
        ):
            self.assertTrue(getattr(boundary, "_is_runtime_protocol", False))

    def test_mapping_is_bidirectional_and_idempotent(self) -> None:
        store = InMemoryVehicleIdMappingStore()
        mapping = self.mapping()

        self.assertIs(store.bind(mapping), mapping)
        self.assertIs(store.bind(self.mapping(mapped_at="later")), mapping)
        self.assertEqual(store.by_local("mac-studio-1", 12), mapping)
        self.assertEqual(store.by_cloud("veh_01K0ABC"), mapping)

    def test_mapping_rejects_local_and_cloud_conflicts(self) -> None:
        store = InMemoryVehicleIdMappingStore()
        store.bind(self.mapping())

        with self.assertRaises(VehicleIdMappingConflict):
            store.bind(self.mapping(cloud_id="veh_other"))
        with self.assertRaises(VehicleIdMappingConflict):
            store.bind(self.mapping(node_id="mac-mini-2", local_id=9))

    def test_unbind_removes_both_indexes(self) -> None:
        store = InMemoryVehicleIdMappingStore()
        store.bind(self.mapping())

        self.assertTrue(store.unbind_local("mac-studio-1", 12))
        self.assertIsNone(store.by_local("mac-studio-1", 12))
        self.assertIsNone(store.by_cloud("veh_01K0ABC"))
        self.assertFalse(store.unbind_local("mac-studio-1", 12))

    def test_event_requires_positive_schema_version(self) -> None:
        with self.assertRaises(ValueError):
            EventEnvelope(
                event_id="evt_1",
                event_type="vehicle.updated",
                occurred_at="2026-07-29T10:00:00Z",
                source_node_id="mac-studio-1",
                schema_version=0,
                data={},
            )

    def test_openapi_schema_exposes_phase_zero_operations(self) -> None:
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "api"
            / "schema"
            / "openapi.v3.0-alpha1.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        self.assertEqual(schema["openapi"], "3.1.0")
        self.assertEqual(schema["info"]["version"], "3.0.0a1")
        self.assertEqual(
            set(schema["paths"]),
            {"/system/status", "/vehicles", "/vehicles/{cloud_id}", "/events"},
        )
        self.assertIn(
            "IdempotencyKey",
            schema["components"]["parameters"],
        )


if __name__ == "__main__":
    unittest.main()
