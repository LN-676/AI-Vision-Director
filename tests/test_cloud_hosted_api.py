from __future__ import annotations

from datetime import datetime, timezone
import unittest

from fastapi.testclient import TestClient

from autocamtracker.api.models import EventResponse, SessionResponse, VehicleResponse
from autocamtracker.api.public_app import create_public_app
from autocamtracker.api.secrets import PublicApiSettings
from autocamtracker.api.write_models import RateLimitDecision


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


class FakeReads:
    def ready(self) -> bool:
        return True

    def list_vehicles(self, *, offset: int, limit: int):
        return (
            [
                VehicleResponse(
                    node_id="edge-1",
                    local_id=7,
                    cloud_id="c071dc11-969e-45bb-b7df-025a567f5d01",
                    display_name="Track Prototype",
                    class_name="car",
                    last_track_id=31,
                    last_frame_index=11602,
                    last_seen_at=NOW,
                    confidence=0.93,
                    bbox=(1, 2, 3, 4),
                    center=(2, 3),
                    created_at=NOW,
                    updated_at=NOW,
                    metadata={},
                )
            ],
            False,
        )

    def list_sessions(self, *, offset: int, limit: int):
        return (
            [
                SessionResponse(
                    session_id="session-1",
                    started_at=NOW,
                    last_event_at=NOW,
                    event_count=1,
                    source_file="telemetry.jsonl",
                )
            ],
            False,
        )

    def list_events(self, *, offset: int, limit: int, session_id: str | None):
        return (
            [
                EventResponse(
                    schema_version=2,
                    session_id="session-1",
                    event="vehicle_lock_acquired",
                    severity="info",
                    component="identity",
                    reason_code=None,
                    timestamp_ms=1785312000000,
                    data={},
                )
            ],
            False,
        )


class AllowLimiter:
    def consume(self, subject: str, route: str) -> RateLimitDecision:
        return RateLimitDecision(True, 0)


class UnusedVerifier:
    def verify(self, token: str):
        raise AssertionError("GET routes must not invoke Firebase verification")


class UnusedWrites:
    def patch_vehicle(self, cloud_id, patch, context):
        raise AssertionError("GET routes must not invoke vehicle writes")


class CloudHostedApiTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = PublicApiSettings(
            database_url="postgresql+psycopg://unused/unused",
            firebase_project_id="bright-torus-483009-k2",
            cors_allow_origins=("https://bright-torus-483009-k2.web.app",),
        )
        self.client = TestClient(
            create_public_app(
                settings,
                token_verifier=UnusedVerifier(),
                vehicle_writes=UnusedWrites(),
                rate_limiter=AllowLimiter(),
                read_store=FakeReads(),
            )
        )

    def test_cloud_status_and_read_routes(self) -> None:
        status = self.client.get("/api/v3/system/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["deployment_mode"], "cloud")
        self.assertEqual(status.json()["status"], "ready")

        self.assertEqual(
            self.client.get("/api/v3/vehicles").json()["items"][0]["local_id"],
            7,
        )
        self.assertEqual(
            self.client.get("/api/v3/sessions").json()["items"][0]["session_id"],
            "session-1",
        )
        self.assertEqual(
            self.client.get("/api/v3/events").json()["items"][0]["event"],
            "vehicle_lock_acquired",
        )

    def test_websocket_rejects_unlisted_origin(self) -> None:
        with self.assertRaises(Exception):
            with self.client.websocket_connect(
                "/ws/telemetry",
                headers={"origin": "https://attacker.example"},
            ):
                pass

    def test_stateless_cost_cap_mode_exposes_empty_read_only_api(self) -> None:
        settings = PublicApiSettings.from_env(
            {
                "AIVD_STATELESS_MODE": "true",
                "AIVD_FIREBASE_PROJECT_ID": "bright-torus-483009-k2",
                "AIVD_CORS_ALLOW_ORIGINS": "https://bright-torus-483009-k2.web.app",
            }
        )
        client = TestClient(create_public_app(settings, token_verifier=UnusedVerifier()))

        status = client.get("/api/v3/system/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["checks"]["postgresql"], "disabled_cost_cap")
        self.assertEqual(status.json()["checks"]["access_mode"], "stateless_read_only")
        self.assertEqual(client.get("/api/v3/vehicles").json()["items"], [])
        self.assertEqual(client.get("/api/v3/sessions").json()["items"], [])
        self.assertEqual(client.get("/api/v3/events").json()["items"], [])


if __name__ == "__main__":
    unittest.main()
