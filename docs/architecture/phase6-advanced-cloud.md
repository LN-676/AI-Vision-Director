# Phase 6: Advanced Cloud Control Plane

Phase 6 extends the authenticated V3 API from a single-node hosted view into an
opt-in multi-tenant control plane. It is deliberately disabled by default:
`enable_advanced_cloud=false` keeps the API stateless and
`enable_gpu_benchmark=false` prevents creation of the L4 job.

## Ownership and access

- `organizations` are the tenant boundary.
- `organization_members` assigns viewer, operator, maintainer, or admin roles.
- `organization_nodes` gives each edge device exactly one owning organization.
- Firebase custom claims carry `organization_ids`; database membership remains
  the source of truth that should be used when issuing those claims.
- Operators can submit benchmarks; maintainers can also manage models, devices,
  and alerts. Cross-organization model/job access is rejected.

## Asynchronous event path

All producers use the versioned `CloudEvent` envelope. Tenant ID is both a
payload field and Pub/Sub ordering key.

1. The API records benchmark intent in PostgreSQL.
2. It starts the CPU or L4 Cloud Run job.
3. Lifecycle events are published to `aivd-benchmark-events`.
4. Operational alerts go to `aivd-alert-events`, with retry and dead lettering.
5. Telemetry events stream to the partitioned and clustered BigQuery
   `aivd_analytics.cloud_events` table for long-term analysis.

The `cloud_event_outbox` table is the durable hand-off point for application
events that must survive a temporary Pub/Sub outage. A dispatcher can claim
pending rows with `FOR UPDATE SKIP LOCKED`, publish them, and set
`published_at`; retries increment `publish_attempts`.

## Model registry and benchmark data

`registered_models` owns the logical model and `model_versions` owns immutable
artifacts. A version stores a `gs://` artifact URI plus its SHA-256 digest and
must be `validated` or `production` before it can run.

The benchmark request points at a dataset manifest in Cloud Storage:

```json
{
  "dataset_version": "golden-v1",
  "video_uri": "gs://bucket/golden/video.mp4",
  "annotations_uri": "gs://bucket/golden/annotations.jsonl"
}
```

The worker downloads the manifest, video, annotations, and registered model,
verifies the model digest, executes the existing deterministic benchmark runner,
uploads the JSON result, updates PostgreSQL, and publishes success/failure.

## Deployment switches

```hcl
enable_advanced_cloud = true
enable_gpu_benchmark  = true
benchmark_image       = "asia-east1-docker.pkg.dev/PROJECT/aivd/benchmark@sha256:..."
alert_email           = "ops@example.com"
```

Run Alembic revision `20260729_0003` before enabling the stateful API. Use
immutable image digests in production. GPU jobs use one NVIDIA L4, four CPUs,
16 GiB RAM, one task, no retry, and non-zonal redundancy to bound parallel spend.
