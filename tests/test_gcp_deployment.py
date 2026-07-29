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

    assert "Dockerfile.cloud" in cloud_build
    assert "dashboard/Dockerfile.cloud" in cloud_build
    assert "/api:${COMMIT_SHA}" in cloud_build
    assert "/dashboard:${COMMIT_SHA}" in cloud_build
    assert "wss://${PROJECT_ID}.web.app/ws/telemetry" in cloud_build
