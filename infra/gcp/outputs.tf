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
