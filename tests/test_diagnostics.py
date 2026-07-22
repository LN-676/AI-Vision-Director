from unittest.mock import patch
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from autocamtracker.core.diagnostics import DiagnosticsService, HealthState
from autocamtracker.core.telemetry_logger import TelemetryLogger


class DiagnosticsServiceTests(unittest.TestCase):
    def test_stale_active_module_becomes_degraded_with_reason(self) -> None:
        service = DiagnosticsService(stale_after_seconds=2.0)
        with patch("autocamtracker.core.diagnostics.monotonic", return_value=10.0):
            service.update("detector", HealthState.HEALTHY, "active")
        with patch("autocamtracker.core.diagnostics.monotonic", return_value=13.0):
            health = service.snapshot()[0]

        self.assertEqual(health.state, HealthState.DEGRADED)
        self.assertEqual(health.reason_code, "HEARTBEAT_STALE")

    def test_fault_state_is_not_hidden_by_staleness(self) -> None:
        service = DiagnosticsService(stale_after_seconds=1.0)
        with patch("autocamtracker.core.diagnostics.monotonic", return_value=1.0):
            service.update("dockkit", HealthState.FAULT, "not ready", reason_code="NOT_READY")
        with patch("autocamtracker.core.diagnostics.monotonic", return_value=100.0):
            health = service.snapshot()[0]

        self.assertEqual(health.state, HealthState.FAULT)
        self.assertEqual(health.reason_code, "NOT_READY")

    def test_telemetry_events_are_structured_and_filterable(self) -> None:
        with TemporaryDirectory() as directory:
            logger = TelemetryLogger(Path(directory), session_name="diagnostics-test")
            logger.log("frame_state", component="pipeline")
            logger.log(
                "camera_frame_decode_failed",
                severity="error",
                component="camera_stream",
                reason_code="DECODE_FAILED",
            )

            events = logger.recent_events(10, minimum_severity="warning")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["schema_version"], 2)
        self.assertEqual(events[0]["component"], "camera_stream")
        self.assertEqual(events[0]["reason_code"], "DECODE_FAILED")


if __name__ == "__main__":
    unittest.main()
