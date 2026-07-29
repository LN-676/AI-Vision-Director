import json
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from autocamtracker.api.auth import principal_from_claims
from autocamtracker.api.public_app import create_public_app
from autocamtracker.api.secrets import PublicApiSettings
from autocamtracker.api.write_models import InMemoryRateLimiter
from autocamtracker.cloud.advanced import (
    BenchmarkJobRequest,
    BenchmarkSubmissionService,
    CloudEvent,
    ModelRegistryService,
    ModelVersionRegistrationRequest,
)


class MemoryStore:
    def __init__(self, model_version_id: str) -> None:
        self.model_version_id = model_version_id
        self.jobs = {}

    def model_version_exists(self, organization_id, model_version_id):
        return model_version_id == self.model_version_id

    def create_benchmark_job(self, job_id, request, actor_uid):
        self.jobs[job_id] = {
            "request": request,
            "actor_uid": actor_uid,
            "status": "pending",
        }

    def mark_benchmark_submitted(self, job_id, execution_name, event_id):
        self.jobs[job_id].update(
            status="submitted",
            execution_name=execution_name,
            event_id=event_id,
        )

    def register_model_version(self, request, actor_uid):
        model_id, version_id = str(uuid4()), str(uuid4())
        self.registered = (model_id, version_id, request, actor_uid)
        return model_id, version_id


class MemoryPublisher:
    def __init__(self) -> None:
        self.messages = []

    def publish(self, topic, event):
        self.messages.append((topic, event))
        return "message-1"


class MemoryLauncher:
    def launch(self, job_id, request):
        return f"operations/{job_id}"


class Verifier:
    def __init__(self, organization_id):
        self.organization_id = organization_id

    def verify(self, token):
        return principal_from_claims(
            {
                "uid": "operator-1",
                "roles": ["operator"],
                "organization_ids": [self.organization_id],
            }
        )


class ReadStore:
    def ready(self):
        return True

    def list_vehicles(self, **kwargs):
        return [], False

    def list_sessions(self, **kwargs):
        return [], False

    def list_events(self, **kwargs):
        return [], False


class Phase6AdvancedCloudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.organization_id = str(uuid4())
        self.model_version_id = str(uuid4())
        self.store = MemoryStore(self.model_version_id)
        self.publisher = MemoryPublisher()
        self.service = BenchmarkSubmissionService(
            self.store, MemoryLauncher(), self.publisher
        )

    def request(self, organization_id=None):
        return BenchmarkJobRequest(
            organization_id=organization_id or self.organization_id,
            model_version_id=self.model_version_id,
            dataset_uri="gs://aivd-data/golden/manifest.json",
            output_uri="gs://aivd-results/jobs/result.json",
            accelerator="nvidia-l4",
            repetitions=3,
        )

    def test_submission_is_tenant_scoped_and_publishes_versioned_event(self):
        principal = principal_from_claims(
            {
                "uid": "operator-1",
                "roles": ["operator"],
                "organization_ids": [self.organization_id],
            }
        )
        response = self.service.submit(self.request(), principal)

        self.assertEqual(response.status, "submitted")
        self.assertEqual(response.accelerator, "nvidia-l4")
        topic, event = self.publisher.messages[0]
        self.assertEqual(topic, "aivd-benchmark-events")
        self.assertEqual(event.event_type, "benchmark.job.submitted")
        self.assertEqual(event.organization_id, self.organization_id)
        self.assertEqual(json.loads(event.payload())["schema_version"], 1)
        self.assertEqual(event.attributes()["organization_id"], self.organization_id)

        with self.assertRaises(PermissionError):
            self.service.submit(self.request(str(uuid4())), principal)

    def test_authenticated_api_accepts_cloud_job(self):
        settings = PublicApiSettings(
            database_url="postgresql+psycopg://unused",
            firebase_project_id="project-1",
            cors_allow_origins=("https://console.example.com",),
        )
        client = TestClient(
            create_public_app(
                settings,
                token_verifier=Verifier(self.organization_id),
                rate_limiter=InMemoryRateLimiter(20, 60),
                read_store=ReadStore(),
                benchmark_submissions=self.service,
            )
        )
        try:
            response = client.post(
                "/api/v3/benchmark-jobs",
                headers={"Authorization": "Bearer token"},
                json=self.request().model_dump(),
            )
        finally:
            client.close()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["organization_id"], self.organization_id)

    def test_cloud_event_has_stable_pubsub_and_bigquery_shape(self):
        event = CloudEvent.create(
            "device.offline",
            organization_id="org-1",
            actor_uid="system",
            subject="nodes/edge-1",
            data={"last_seen_seconds": 90},
        )
        payload = json.loads(event.payload())
        self.assertEqual(
            set(payload),
            {
                "event_id",
                "event_type",
                "occurred_at",
                "organization_id",
                "actor_uid",
                "subject",
                "data",
                "schema_version",
                "correlation_id",
            },
        )

    def test_maintainer_can_register_tenant_model_version(self):
        principal = principal_from_claims(
            {
                "uid": "maintainer-1",
                "roles": ["maintainer"],
                "organization_ids": [self.organization_id],
            }
        )
        response = ModelRegistryService(self.store, self.publisher).register(
            ModelVersionRegistrationRequest(
                organization_id=self.organization_id,
                model_name="race-detector",
                task="detection",
                version="2026.07.29",
                artifact_uri="gs://aivd-models/race-detector.onnx",
                digest_sha256="a" * 64,
                runtime="onnx",
            ),
            principal,
        )
        self.assertEqual(response.status, "candidate")
        self.assertEqual(
            self.publisher.messages[-1][1].event_type,
            "model.version.registered",
        )


if __name__ == "__main__":
    unittest.main()
