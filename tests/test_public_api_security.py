from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from autocamtracker.api.auth import (
    FirebaseTokenVerifier,
    Principal,
    principal_from_claims,
)
from autocamtracker.api.public_app import create_public_app
from autocamtracker.api.secrets import PublicApiSettings
from autocamtracker.api.write_models import (
    InMemoryRateLimiter,
    VehicleWriteResponse,
)


class FakeVerifier:
    def verify(self, token: str) -> Principal:
        if token == "operator-token":
            return principal_from_claims(
                {"uid": "user-1", "roles": ["operator"], "node_ids": ["edge-1"]}
            )
        if token == "viewer-token":
            return principal_from_claims({"uid": "user-2", "role": "viewer"})
        raise ValueError("invalid token")


class FakeVehicleWrites:
    def __init__(self) -> None:
        self.calls = []

    def patch_vehicle(self, cloud_id, patch, audit) -> VehicleWriteResponse:
        self.calls.append((cloud_id, patch, audit))
        return VehicleWriteResponse(
            cloud_id=cloud_id,
            node_id="edge-1",
            local_id=1,
            display_name=patch.display_name or "Existing",
            metadata=patch.metadata or {},
            updated_at="2026-07-29T12:01:00Z",
            audit_id=str(uuid4()),
        )


class PublicApiSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = PublicApiSettings(
            database_url="postgresql+psycopg://unused",
            firebase_project_id="test-project",
            cors_allow_origins=("https://console.example.com",),
            rate_limit_requests=10,
            rate_limit_window_seconds=60,
        )
        self.writes = FakeVehicleWrites()
        self.client = TestClient(
            create_public_app(
                self.settings,
                token_verifier=FakeVerifier(),
                vehicle_writes=self.writes,
                rate_limiter=InMemoryRateLimiter(10, 60),
            )
        )
        self.cloud_id = str(uuid4())
        self.body = {
            "expected_updated_at": "2026-07-29T12:00:00Z",
            "display_name": "Updated",
        }

    def tearDown(self) -> None:
        self.client.close()

    def patch(self, token: str | None, *, key: str = "request-1234"):
        headers = {"Idempotency-Key": key}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return self.client.patch(
            f"/api/v3/vehicles/{self.cloud_id}",
            json=self.body,
            headers=headers,
        )

    def test_missing_invalid_and_revoked_tokens_are_unauthorized(self) -> None:
        self.assertEqual(self.patch(None).status_code, 401)
        response = self.patch("bad-token")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(self.writes.calls, [])

    def test_viewer_cannot_patch_vehicle(self) -> None:
        response = self.patch("viewer-token")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.writes.calls, [])

    def test_operator_patch_passes_audit_identity_and_returns_headers(self) -> None:
        response = self.patch("operator-token")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display_name"], "Updated")
        self.assertEqual(response.headers["x-audit-id"], response.json()["audit_id"])
        self.assertEqual(response.headers["etag"], '"2026-07-29T12:01:00Z"')
        _, _, audit = self.writes.calls[0]
        self.assertEqual(audit.actor.uid, "user-1")
        self.assertEqual(audit.request_id, "request-1234")
        self.assertNotIn("operator-token", repr(audit))

    def test_rate_limit_returns_429_and_retry_after(self) -> None:
        client = TestClient(
            create_public_app(
                self.settings,
                token_verifier=FakeVerifier(),
                vehicle_writes=self.writes,
                rate_limiter=InMemoryRateLimiter(1, 60),
            )
        )
        try:
            self.assertEqual(
                client.patch(
                    f"/api/v3/vehicles/{self.cloud_id}",
                    json=self.body,
                    headers={
                        "Authorization": "Bearer operator-token",
                        "Idempotency-Key": "request-first",
                    },
                ).status_code,
                200,
            )
            response = client.patch(
                f"/api/v3/vehicles/{self.cloud_id}",
                json=self.body,
                headers={
                    "Authorization": "Bearer operator-token",
                    "Idempotency-Key": "request-second",
                },
            )
        finally:
            client.close()

        self.assertEqual(response.status_code, 429)
        self.assertGreaterEqual(int(response.headers["retry-after"]), 1)

    def test_cors_is_an_explicit_allowlist(self) -> None:
        allowed = self.client.options(
            f"/api/v3/vehicles/{self.cloud_id}",
            headers={
                "Origin": "https://console.example.com",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": "authorization,idempotency-key",
            },
        )
        denied = self.client.options(
            f"/api/v3/vehicles/{self.cloud_id}",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "PATCH",
            },
        )

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(
            allowed.headers["access-control-allow-origin"],
            "https://console.example.com",
        )
        self.assertEqual(denied.status_code, 400)
        self.assertNotIn("access-control-allow-origin", denied.headers)

    def test_openapi_declares_bearer_auth_on_the_only_write_operation(self) -> None:
        schema = self.client.get("/openapi.json").json()

        operation = schema["paths"]["/api/v3/vehicles/{cloud_id}"]["patch"]
        self.assertTrue(operation["security"])
        self.assertEqual(
            set(schema["components"]["securitySchemes"]),
            {"HTTPBearer"},
        )
        methods = {
            method
            for path in schema["paths"].values()
            for method in path
            if method in {"post", "put", "patch", "delete"}
        }
        self.assertEqual(methods, {"patch", "post"})


class PrincipalAndSecretTests(unittest.TestCase):
    def test_firebase_verifier_enables_revocation_check(self) -> None:
        verifier = FirebaseTokenVerifier("aivd-unit-test-project")
        with patch(
            "firebase_admin.auth.verify_id_token",
            return_value={"uid": "user-1", "roles": ["operator"]},
        ) as verify:
            principal = verifier.verify("signed-token")

        self.assertEqual(principal.uid, "user-1")
        self.assertTrue(verify.call_args.kwargs["check_revoked"])
        self.assertNotEqual(verify.call_args.kwargs["app"], None)

    def test_admin_and_operator_claims_map_to_permissions(self) -> None:
        operator = principal_from_claims(
            {"sub": "operator-1", "roles": ["operator"], "node_ids": ["edge-1"]}
        )
        admin = principal_from_claims({"uid": "admin-1", "admin": True})

        self.assertTrue(operator.has_permission("vehicle:write"))
        self.assertTrue(operator.can_access_node("edge-1"))
        self.assertFalse(operator.can_access_node("edge-2"))
        self.assertTrue(admin.has_permission("anything"))
        self.assertTrue(admin.can_access_node("edge-2"))

    def test_secret_file_and_cors_validation_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            secret = Path(directory) / "database-url"
            secret.write_text("postgresql+psycopg://secret", encoding="utf-8")
            settings = PublicApiSettings.from_env(
                {
                    "AIVD_DATABASE_URL_FILE": str(secret),
                    "AIVD_FIREBASE_PROJECT_ID": "project-1",
                    "AIVD_CORS_ALLOW_ORIGINS": "https://console.example.com",
                }
            )
        self.assertEqual(settings.database_url, "postgresql+psycopg://secret")
        self.assertNotIn("postgresql+psycopg://secret", repr(settings))
        with self.assertRaises(ValueError):
            PublicApiSettings.from_env(
                {
                    "AIVD_DATABASE_URL": "postgresql://secret",
                    "AIVD_FIREBASE_PROJECT_ID": "project-1",
                    "AIVD_CORS_ALLOW_ORIGINS": "*",
                }
            )
        with self.assertRaises(ValueError):
            PublicApiSettings.from_env({})


if __name__ == "__main__":
    unittest.main()
