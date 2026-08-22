import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_terraform_covers_phase_5_services_and_cost_controls() -> None:
    terraform = (ROOT / "infra/gcp/main.tf").read_text(encoding="utf-8")

    for resource in (
        'resource "google_artifact_registry_repository"',
        'resource "google_storage_bucket"',
        'resource "google_sql_database_instance"',
        'resource "google_cloud_run_v2_service" "api"',
        'resource "google_cloud_run_v2_service" "dashboard"',
        'resource "google_pubsub_topic" "billing"',
        'resource "google_billing_budget" "notifications"',
        'resource "google_monitoring_alert_policy" "api_errors"',
    ):
        assert resource in terraform

    assert 'name                       = "aivd-billing-alerts"' in terraform
    assert 'currency_code = "USD"' in terraform
    assert 'units         = "1"' in terraform
    assert "max_instance_count = 1" in terraform
    assert "deletion_protection = true" in terraform


def test_firebase_routes_api_and_dashboard_to_separate_cloud_run_services() -> None:
    config = json.loads((ROOT / "firebase.json").read_text(encoding="utf-8"))
    rewrites = config["hosting"]["rewrites"]

    assert rewrites[0]["source"] == "/api/**"
    assert rewrites[0]["run"]["serviceId"] == "aivd-api"
    assert rewrites[1]["source"] == "/**"
    assert rewrites[1]["run"]["serviceId"] == "aivd-dashboard"
    assert all(rewrite["run"]["region"] == "asia-east1" for rewrite in rewrites)


def test_cloud_build_publishes_api_and_dashboard_images() -> None:
    cloud_build = (ROOT / "cloudbuild.yaml").read_text(encoding="utf-8")

    assert "docker/Dockerfile.api" in cloud_build
    assert "dashboard/Dockerfile" in cloud_build
    assert "docker/Dockerfile.benchmark" in cloud_build
    assert "/api:${COMMIT_SHA}" in cloud_build
    assert "/dashboard:${COMMIT_SHA}" in cloud_build
    assert "/benchmark:${COMMIT_SHA}" in cloud_build
    assert "wss://${PROJECT_ID}.web.app/ws/telemetry" in cloud_build


def test_phase6_advanced_cloud_infrastructure_is_cost_gated() -> None:
    terraform = (ROOT / "infra/gcp/main.tf").read_text(encoding="utf-8")
    variables = (ROOT / "infra/gcp/variables.tf").read_text(encoding="utf-8")

    for resource in (
        'resource "google_pubsub_topic" "telemetry"',
        'resource "google_pubsub_topic" "benchmark"',
        'resource "google_pubsub_topic" "alerts"',
        'resource "google_pubsub_topic" "dead_letter"',
        'resource "google_bigquery_dataset" "analytics"',
        'resource "google_bigquery_table" "cloud_events"',
        'resource "google_pubsub_subscription" "telemetry_bigquery"',
        'resource "google_cloud_run_v2_job" "benchmark_cpu"',
        'resource "google_cloud_run_v2_job" "benchmark_gpu"',
        'resource "google_monitoring_alert_policy" "benchmark_failures"',
    ):
        assert resource in terraform

    assert 'variable "enable_gpu_benchmark"' in variables
    assert 'variable "enable_advanced_cloud"' in variables
    assert "default     = false" in variables
    assert 'accelerator = "nvidia-l4"' in terraform
    assert '"nvidia.com/gpu" = "1"' in terraform
