"""Cloud Run worker for one recorded Phase 6 benchmark job."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import and_, create_engine, select, update

from autocamtracker.cloud.advanced import CloudEvent, GooglePubSubPublisher
from autocamtracker.cloud.postgres_schema import (
    benchmark_jobs,
    model_versions,
    registered_models,
)
from autocamtracker.evaluation.benchmark import save_results
from autocamtracker.evaluation.vision_benchmark import (
    VisionBenchmarkRequest,
    VisionBenchmarkRunner,
)


def _gcs_parts(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"invalid Cloud Storage URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _download(client, uri: str, destination: Path) -> None:
    bucket, name = _gcs_parts(uri)
    destination.parent.mkdir(parents=True, exist_ok=True)
    client.bucket(bucket).blob(name).download_to_filename(destination)


def _upload(client, source: Path, uri: str) -> None:
    bucket, name = _gcs_parts(uri)
    client.bucket(bucket).blob(name).upload_from_filename(
        source, content_type="application/json"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_job(job_id: str, database_url: str, project_id: str) -> None:
    from google.cloud import storage

    engine = create_engine(database_url, pool_pre_ping=True)
    publisher = GooglePubSubPublisher(project_id)
    storage_client = storage.Client(project=project_id)
    job_uuid = UUID(job_id)
    statement = (
        select(
            benchmark_jobs,
            model_versions.c.artifact_uri,
            model_versions.c.digest_sha256,
            registered_models.c.organization_id.label("model_organization_id"),
        )
        .join(
            model_versions,
            model_versions.c.model_version_id == benchmark_jobs.c.model_version_id,
        )
        .join(
            registered_models,
            registered_models.c.model_id == model_versions.c.model_id,
        )
        .where(benchmark_jobs.c.job_id == job_uuid)
    )
    with engine.begin() as connection:
        row = connection.execute(statement).mappings().one()
        if row["organization_id"] != row["model_organization_id"]:
            raise PermissionError("benchmark model is outside the organization")
        connection.execute(
            update(benchmark_jobs)
            .where(
                and_(
                    benchmark_jobs.c.job_id == job_uuid,
                    benchmark_jobs.c.status.in_(("pending", "submitted")),
                )
            )
            .values(status="running")
        )

    try:
        with TemporaryDirectory(prefix="aivd-benchmark-") as directory:
            root = Path(directory)
            manifest_path = root / "dataset.json"
            model_name = Path(_gcs_parts(row["artifact_uri"])[1]).name
            model_path = root / (model_name or "model.onnx")
            annotations_path = root / "annotations.jsonl"
            output_path = root / "result.json"
            _download(storage_client, row["dataset_uri"], manifest_path)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            video_name = Path(_gcs_parts(manifest["video_uri"])[1]).name
            video_path = root / (video_name or "video.mp4")
            _download(storage_client, manifest["video_uri"], video_path)
            _download(storage_client, manifest["annotations_uri"], annotations_path)
            _download(storage_client, row["artifact_uri"], model_path)
            if _sha256(model_path) != row["digest_sha256"].lower():
                raise ValueError("model SHA-256 digest mismatch")

            all_results = []
            for _ in range(row["repetitions"]):
                all_results.extend(
                    VisionBenchmarkRunner().run(
                        VisionBenchmarkRequest(
                            video_path=video_path,
                            annotation_path=annotations_path,
                            model_paths=(model_path,),
                            dataset_version=manifest.get("dataset_version", "cloud-v1"),
                        )
                    )
                )
            save_results(output_path, all_results)
            _upload(storage_client, output_path, row["output_uri"])
        status = "succeeded"
        result = {"output_uri": row["output_uri"], "runs": len(all_results)}
        error_message = None
    except Exception as error:
        status = "failed"
        result = {}
        error_message = f"{type(error).__name__}: {error}"[:4000]
        raise
    finally:
        from datetime import datetime, timezone

        with engine.begin() as connection:
            connection.execute(
                update(benchmark_jobs)
                .where(benchmark_jobs.c.job_id == job_uuid)
                .values(
                    status=status,
                    result=result,
                    error_message=error_message,
                    finished_at=datetime.now(timezone.utc),
                )
            )
        event = CloudEvent.create(
            f"benchmark.job.{status}",
            organization_id=str(row["organization_id"]),
            actor_uid="cloud-run-worker",
            subject=f"benchmark_jobs/{job_id}",
            correlation_id=job_id,
            data={"job_id": job_id, "status": status, **result},
        )
        publisher.publish("aivd-benchmark-events", event)
        if status == "failed":
            publisher.publish("aivd-alert-events", event)
        engine.dispose()


def main() -> int:
    job_id = os.environ.get("AIVD_BENCHMARK_JOB_ID", "").strip()
    database_url = os.environ.get("AIVD_DATABASE_URL", "").strip()
    project_id = os.environ.get("AIVD_FIREBASE_PROJECT_ID", "").strip()
    if not job_id or not database_url or not project_id:
        raise RuntimeError(
            "AIVD_BENCHMARK_JOB_ID, AIVD_DATABASE_URL, and "
            "AIVD_FIREBASE_PROJECT_ID are required"
        )
    run_job(job_id, database_url, project_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
