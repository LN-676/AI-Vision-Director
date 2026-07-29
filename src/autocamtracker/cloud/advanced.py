"""Phase 6 cloud control-plane contracts.

The module keeps Google SDK details behind small ports so API and domain tests do
not require cloud credentials. Every asynchronous action emits the same
versioned CloudEvent envelope, which can be routed to Pub/Sub and BigQuery.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Engine, and_, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.exc import IntegrityError

from autocamtracker.api.auth import Principal
from autocamtracker.cloud.postgres_schema import (
    benchmark_jobs,
    model_versions,
    registered_models,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class CloudEvent:
    event_id: str
    event_type: str
    occurred_at: str
    organization_id: str
    actor_uid: str
    subject: str
    data: dict[str, Any]
    schema_version: int = 1
    correlation_id: str | None = None

    @classmethod
    def create(
        cls,
        event_type: str,
        *,
        organization_id: str,
        actor_uid: str,
        subject: str,
        data: dict[str, Any],
        correlation_id: str | None = None,
    ) -> "CloudEvent":
        return cls(
            event_id=str(uuid4()),
            event_type=event_type,
            occurred_at=utc_now().isoformat().replace("+00:00", "Z"),
            organization_id=organization_id,
            actor_uid=actor_uid,
            subject=subject,
            data=data,
            correlation_id=correlation_id,
        )

    def attributes(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "organization_id": self.organization_id,
            "schema_version": str(self.schema_version),
        }

    def payload(self) -> bytes:
        return json.dumps(
            asdict(self), separators=(",", ":"), sort_keys=True
        ).encode("utf-8")


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, topic: str, event: CloudEvent) -> str: ...


@runtime_checkable
class BenchmarkLauncher(Protocol):
    def launch(self, job_id: str, request: "BenchmarkJobRequest") -> str: ...


@runtime_checkable
class AdvancedControlStore(Protocol):
    def model_version_exists(
        self, organization_id: str, model_version_id: str
    ) -> bool: ...

    def create_benchmark_job(
        self,
        job_id: str,
        request: "BenchmarkJobRequest",
        actor_uid: str,
    ) -> None: ...

    def mark_benchmark_submitted(
        self, job_id: str, execution_name: str, event_id: str
    ) -> None: ...

    def register_model_version(
        self,
        request: "ModelVersionRegistrationRequest",
        actor_uid: str,
    ) -> tuple[str, str]: ...

    def update_model_version_status(
        self,
        organization_id: str,
        model_version_id: str,
        status: str,
        metrics: dict[str, Any],
    ) -> bool: ...


class BenchmarkJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str = Field(min_length=1, max_length=255)
    model_version_id: str
    dataset_uri: str = Field(pattern=r"^gs://[^/]+/.+")
    output_uri: str = Field(pattern=r"^gs://[^/]+/.+")
    accelerator: Literal["cpu", "nvidia-l4"] = "cpu"
    repetitions: int = Field(default=1, ge=1, le=20)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("model_version_id")
    @classmethod
    def valid_model_version_id(cls, value: str) -> str:
        UUID(value)
        return value

    @field_validator("organization_id")
    @classmethod
    def valid_organization_id(cls, value: str) -> str:
        UUID(value)
        return value

    @field_validator("labels")
    @classmethod
    def valid_labels(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 32:
            raise ValueError("at most 32 labels are allowed")
        if any(len(key) > 63 or len(item) > 63 for key, item in value.items()):
            raise ValueError("label keys and values must be at most 63 characters")
        return value


class BenchmarkJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    organization_id: str
    status: Literal["submitted"]
    accelerator: Literal["cpu", "nvidia-l4"]
    execution_name: str
    event_id: str


class ModelVersionRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str
    model_name: str = Field(min_length=1, max_length=255)
    task: Literal["detection", "reid", "tracking", "framing"]
    version: str = Field(min_length=1, max_length=100)
    artifact_uri: str = Field(pattern=r"^gs://[^/]+/.+")
    digest_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    runtime: Literal["onnx", "tensorrt", "pytorch", "coreml"]
    description: str | None = Field(default=None, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("organization_id")
    @classmethod
    def valid_organization_id(cls, value: str) -> str:
        UUID(value)
        return value


class ModelVersionRegistrationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    model_version_id: str
    organization_id: str
    status: Literal["candidate"]
    event_id: str


class ModelVersionStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str
    status: Literal["validated", "production", "retired"]
    metrics: dict[str, float] = Field(default_factory=dict)

    @field_validator("organization_id")
    @classmethod
    def valid_organization_id(cls, value: str) -> str:
        UUID(value)
        return value

    @field_validator("metrics")
    @classmethod
    def finite_metrics(cls, value: dict[str, float]) -> dict[str, float]:
        from math import isfinite

        if len(value) > 100 or any(not isfinite(item) for item in value.values()):
            raise ValueError("metrics must contain at most 100 finite values")
        return value


class ModelVersionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version_id: str
    organization_id: str
    status: Literal["validated", "production", "retired"]
    event_id: str


class OrganizationScopeDenied(PermissionError):
    pass


class ModelVersionNotFound(LookupError):
    pass


class ModelRegistryConflict(RuntimeError):
    pass


class BenchmarkSubmissionService:
    """Atomically records intent before launching and emits a lifecycle event."""

    def __init__(
        self,
        store: AdvancedControlStore,
        launcher: BenchmarkLauncher,
        publisher: EventPublisher,
        *,
        lifecycle_topic: str = "aivd-benchmark-events",
    ) -> None:
        self.store = store
        self.launcher = launcher
        self.publisher = publisher
        self.lifecycle_topic = lifecycle_topic

    def submit(
        self, request: BenchmarkJobRequest, principal: Principal
    ) -> BenchmarkJobResponse:
        if (
            "admin" not in principal.roles
            and request.organization_id not in principal.organization_ids
        ):
            raise OrganizationScopeDenied(request.organization_id)
        if not principal.has_permission("benchmark:create"):
            raise PermissionError("benchmark:create permission required")
        if not self.store.model_version_exists(
            request.organization_id, request.model_version_id
        ):
            raise ModelVersionNotFound(request.model_version_id)

        job_id = str(uuid4())
        self.store.create_benchmark_job(job_id, request, principal.uid)
        execution_name = self.launcher.launch(job_id, request)
        event = CloudEvent.create(
            "benchmark.job.submitted",
            organization_id=request.organization_id,
            actor_uid=principal.uid,
            subject=f"benchmark_jobs/{job_id}",
            correlation_id=job_id,
            data={
                "job_id": job_id,
                "model_version_id": request.model_version_id,
                "accelerator": request.accelerator,
                "execution_name": execution_name,
            },
        )
        self.publisher.publish(self.lifecycle_topic, event)
        self.store.mark_benchmark_submitted(job_id, execution_name, event.event_id)
        return BenchmarkJobResponse(
            job_id=job_id,
            organization_id=request.organization_id,
            status="submitted",
            accelerator=request.accelerator,
            execution_name=execution_name,
            event_id=event.event_id,
        )


class ModelRegistryService:
    def __init__(
        self,
        store: AdvancedControlStore,
        publisher: EventPublisher,
        *,
        lifecycle_topic: str = "aivd-benchmark-events",
    ) -> None:
        self.store = store
        self.publisher = publisher
        self.lifecycle_topic = lifecycle_topic

    def register(
        self, request: ModelVersionRegistrationRequest, principal: Principal
    ) -> ModelVersionRegistrationResponse:
        if (
            "admin" not in principal.roles
            and request.organization_id not in principal.organization_ids
        ):
            raise OrganizationScopeDenied(request.organization_id)
        if not principal.has_permission("model:write"):
            raise PermissionError("model:write permission required")
        model_id, version_id = self.store.register_model_version(
            request, principal.uid
        )
        event = CloudEvent.create(
            "model.version.registered",
            organization_id=request.organization_id,
            actor_uid=principal.uid,
            subject=f"model_versions/{version_id}",
            correlation_id=version_id,
            data={
                "model_id": model_id,
                "model_version_id": version_id,
                "version": request.version,
                "runtime": request.runtime,
                "status": "candidate",
            },
        )
        self.publisher.publish(self.lifecycle_topic, event)
        return ModelVersionRegistrationResponse(
            model_id=model_id,
            model_version_id=version_id,
            organization_id=request.organization_id,
            status="candidate",
            event_id=event.event_id,
        )

    def update_status(
        self,
        model_version_id: str,
        request: ModelVersionStatusRequest,
        principal: Principal,
    ) -> ModelVersionStatusResponse:
        UUID(model_version_id)
        if (
            "admin" not in principal.roles
            and request.organization_id not in principal.organization_ids
        ):
            raise OrganizationScopeDenied(request.organization_id)
        if not principal.has_permission("model:write"):
            raise PermissionError("model:write permission required")
        updated = self.store.update_model_version_status(
            request.organization_id,
            model_version_id,
            request.status,
            request.metrics,
        )
        if not updated:
            raise ModelVersionNotFound(model_version_id)
        event = CloudEvent.create(
            "model.version.status_changed",
            organization_id=request.organization_id,
            actor_uid=principal.uid,
            subject=f"model_versions/{model_version_id}",
            correlation_id=model_version_id,
            data={
                "model_version_id": model_version_id,
                "status": request.status,
                "metrics": request.metrics,
            },
        )
        self.publisher.publish(self.lifecycle_topic, event)
        return ModelVersionStatusResponse(
            model_version_id=model_version_id,
            organization_id=request.organization_id,
            status=request.status,
            event_id=event.event_id,
        )


class GooglePubSubPublisher:
    """Production publisher with ordering by tenant and a future-like timeout."""

    def __init__(self, project_id: str, *, timeout_seconds: float = 10.0) -> None:
        from google.cloud import pubsub_v1

        self.project_id = project_id
        self.timeout_seconds = timeout_seconds
        self.client = pubsub_v1.PublisherClient(
            publisher_options=pubsub_v1.types.PublisherOptions(
                enable_message_ordering=True
            )
        )

    def publish(self, topic: str, event: CloudEvent) -> str:
        topic_path = (
            topic if topic.startswith("projects/") else self.client.topic_path(self.project_id, topic)
        )
        future = self.client.publish(
            topic_path,
            event.payload(),
            ordering_key=event.organization_id,
            **event.attributes(),
        )
        return str(future.result(timeout=self.timeout_seconds))


class PostgresAdvancedControlStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def model_version_exists(
        self, organization_id: str, model_version_id: str
    ) -> bool:
        statement = (
            select(model_versions.c.model_version_id)
            .join(
                registered_models,
                registered_models.c.model_id == model_versions.c.model_id,
            )
            .where(
                and_(
                    registered_models.c.organization_id == UUID(organization_id),
                    model_versions.c.model_version_id == UUID(model_version_id),
                    model_versions.c.status.in_(("validated", "production")),
                )
            )
        )
        with self.engine.connect() as connection:
            return connection.execute(statement).first() is not None

    def create_benchmark_job(
        self,
        job_id: str,
        request: BenchmarkJobRequest,
        actor_uid: str,
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(benchmark_jobs).values(
                    job_id=UUID(job_id),
                    organization_id=UUID(request.organization_id),
                    model_version_id=UUID(request.model_version_id),
                    created_by=actor_uid,
                    status="pending",
                    accelerator=request.accelerator,
                    dataset_uri=request.dataset_uri,
                    output_uri=request.output_uri,
                    repetitions=request.repetitions,
                    metadata={"labels": request.labels},
                )
            )

    def mark_benchmark_submitted(
        self, job_id: str, execution_name: str, event_id: str
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                update(benchmark_jobs)
                .where(benchmark_jobs.c.job_id == UUID(job_id))
                .values(
                    status="submitted",
                    execution_name=execution_name,
                    submitted_event_id=UUID(event_id),
                )
            )

    def register_model_version(
        self,
        request: ModelVersionRegistrationRequest,
        actor_uid: str,
    ) -> tuple[str, str]:
        organization_id = UUID(request.organization_id)
        proposed_model_id = uuid4()
        version_id = uuid4()
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    postgres_insert(registered_models)
                    .values(
                        model_id=proposed_model_id,
                        organization_id=organization_id,
                        name=request.model_name,
                        task=request.task,
                        description=request.description,
                        created_by=actor_uid,
                        metadata=request.metadata,
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_registered_models_org_name"
                    )
                )
                model_row = connection.execute(
                    select(
                        registered_models.c.model_id,
                        registered_models.c.task == request.task,
                    )
                    .where(
                        and_(
                            registered_models.c.organization_id == organization_id,
                            registered_models.c.name == request.model_name,
                        )
                    )
                ).one()
                model_id, task_matches = model_row
                if not task_matches:
                    raise ModelRegistryConflict(
                        "model name already exists with a different task"
                    )
                connection.execute(
                    insert(model_versions).values(
                        model_version_id=version_id,
                        model_id=model_id,
                        version=request.version,
                        artifact_uri=request.artifact_uri,
                        digest_sha256=request.digest_sha256.lower(),
                        runtime=request.runtime,
                        status="candidate",
                        created_by=actor_uid,
                        metrics={},
                    )
                )
        except IntegrityError as error:
            raise ModelRegistryConflict("model version already exists") from error
        return str(model_id), str(version_id)

    def update_model_version_status(
        self,
        organization_id: str,
        model_version_id: str,
        status: str,
        metrics: dict[str, Any],
    ) -> bool:
        statement = (
            update(model_versions)
            .where(
                and_(
                    model_versions.c.model_version_id == UUID(model_version_id),
                    model_versions.c.model_id.in_(
                        select(registered_models.c.model_id).where(
                            registered_models.c.organization_id
                            == UUID(organization_id)
                        )
                    ),
                )
            )
            .values(status=status, metrics=metrics)
        )
        with self.engine.begin() as connection:
            return connection.execute(statement).rowcount == 1


class GoogleCloudRunBenchmarkLauncher:
    """Starts one of two immutable Cloud Run job templates with safe overrides."""

    def __init__(
        self,
        project_id: str,
        *,
        cpu_region: str = "asia-east1",
        gpu_region: str = "asia-southeast1",
    ) -> None:
        from google.cloud import run_v2

        self.project_id = project_id
        self.cpu_region = cpu_region
        self.gpu_region = gpu_region
        self.client = run_v2.JobsClient()

    def launch(self, job_id: str, request: BenchmarkJobRequest) -> str:
        region = self.gpu_region if request.accelerator == "nvidia-l4" else self.cpu_region
        job_name = (
            "aivd-benchmark-gpu"
            if request.accelerator == "nvidia-l4"
            else "aivd-benchmark-cpu"
        )
        name = f"projects/{self.project_id}/locations/{region}/jobs/{job_name}"
        operation = self.client.run_job(
            request={
                "name": name,
                "overrides": {
                    "container_overrides": [
                        {
                            "env": [
                                {"name": "AIVD_BENCHMARK_JOB_ID", "value": job_id},
                                {
                                    "name": "AIVD_ORGANIZATION_ID",
                                    "value": request.organization_id,
                                },
                                {
                                    "name": "AIVD_BENCHMARK_REPETITIONS",
                                    "value": str(request.repetitions),
                                },
                            ],
                        }
                    ],
                    "task_count": 1,
                    "timeout": "3600s",
                },
            }
        )
        return operation.operation.name
