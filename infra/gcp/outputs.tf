output "api_url" {
  value = google_cloud_run_v2_service.api.uri
}

output "dashboard_url" {
  value = google_cloud_run_v2_service.dashboard.uri
}

output "artifact_registry" {
  value = google_artifact_registry_repository.containers.name
}

output "storage_bucket" {
  value = google_storage_bucket.artifacts.name
}

output "billing_topic" {
  value = google_pubsub_topic.billing.id
}

output "cloud_sql_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "migration_job" {
  value = google_cloud_run_v2_job.migrations.name
}

output "benchmark_cpu_job" {
  value = google_cloud_run_v2_job.benchmark_cpu.name
}

output "benchmark_gpu_job" {
  value = try(google_cloud_run_v2_job.benchmark_gpu[0].name, null)
}

output "analytics_table" {
  value = "${var.project_id}.${google_bigquery_dataset.analytics.dataset_id}.${google_bigquery_table.cloud_events.table_id}"
}

output "event_topics" {
  value = {
    telemetry = google_pubsub_topic.telemetry.id
    benchmark = google_pubsub_topic.benchmark.id
    alerts    = google_pubsub_topic.alerts.id
  }
}
