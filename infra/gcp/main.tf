locals {
  name              = "aivd-v3"
  database_name     = "aivd"
  database_user     = "aivd_api"
  api_service       = "aivd-api"
  dashboard_service = "aivd-dashboard"
  benchmark_image    = var.benchmark_image == "" ? var.api_image : var.benchmark_image
  required_apis = toset([
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbilling.googleapis.com",
    "firebase.googleapis.com",
    "firebasehosting.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
  ])
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "required" {
  for_each           = local.required_apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "aivd"
  description   = "AI Vision Director production containers"
  format        = "DOCKER"
  depends_on    = [google_project_service.required]
}

resource "google_storage_bucket" "artifacts" {
  name                        = "${var.project_id}-aivd-artifacts"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }
}

resource "random_password" "database" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "postgres" {
  name                = "${local.name}-postgres"
  region              = var.region
  database_version    = "POSTGRES_17"
  deletion_protection = true

  settings {
    tier              = "db-f1-micro"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "18:00"
      transaction_log_retention_days = 7
    }

    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }

    insights_config {
      query_insights_enabled  = true
      record_application_tags = true
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_sql_database" "app" {
  name     = local.database_name
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "app" {
  name     = local.database_user
  instance = google_sql_database_instance.postgres.name
  password = random_password.database.result
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "aivd-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  secret_data = format(
    "postgresql+psycopg://%s:%s@/%s?host=/cloudsql/%s",
    local.database_user,
    random_password.database.result,
    local.database_name,
    google_sql_database_instance.postgres.connection_name,
  )
}

resource "google_service_account" "runtime" {
  account_id   = "aivd-cloud-run"
  display_name = "AI Vision Director Cloud Run"
}

resource "google_project_iam_member" "runtime_roles" {
  for_each = toset([
    "roles/bigquery.dataEditor",
    "roles/cloudsql.client",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/pubsub.publisher",
    "roles/run.invoker",
    "roles/storage.objectUser",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service" "api" {
  name                = local.api_service
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runtime.email
    timeout         = "3600s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.api_image

      ports {
        container_port = 8080
      }

      env {
        name  = "AIVD_FIREBASE_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "AIVD_CORS_ALLOW_ORIGINS"
        value = var.cors_allow_origins
      }
      env {
        name  = "AIVD_FORWARDED_ALLOW_IPS"
        value = "169.254.8.129"
      }
      env {
        name  = "AIVD_STATELESS_MODE"
        value = var.enable_advanced_cloud ? "false" : "true"
      }
      env {
        name  = "AIVD_CLOUD_REGION"
        value = var.region
      }
      env {
        name  = "AIVD_GPU_REGION"
        value = var.gpu_region
      }
      env {
        name = "AIVD_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        failure_threshold     = 12
        period_seconds        = 5
        initial_delay_seconds = 2
        timeout_seconds       = 3
        http_get {
          path = "/healthz"
          port = 8080
        }
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.database_url,
  ]
}

resource "google_cloud_run_v2_job" "migrations" {
  name                = "aivd-migrations"
  location            = var.region
  deletion_protection = true

  template {
    template {
      service_account = google_service_account.runtime.email
      max_retries     = 1
      timeout         = "600s"

      containers {
        image   = var.api_image
        command = ["alembic"]
        args    = ["upgrade", "head"]

        env {
          name = "AIVD_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.postgres.connection_name]
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.database_url,
  ]
}

resource "google_cloud_run_v2_service" "dashboard" {
  name                = local.dashboard_service
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runtime.email
    timeout         = "3600s"
    session_affinity = true

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.dashboard_image
      ports {
        container_port = 8080
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "dashboard_public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.dashboard.location
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_pubsub_topic" "billing" {
  name                       = "aivd-billing-alerts"
  message_retention_duration = "604800s"
  depends_on                 = [google_project_service.required]
}

resource "google_pubsub_topic" "telemetry" {
  name                       = "aivd-telemetry-events"
  message_retention_duration = "604800s"
  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "benchmark" {
  name                       = "aivd-benchmark-events"
  message_retention_duration = "604800s"
  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "alerts" {
  name                       = "aivd-alert-events"
  message_retention_duration = "604800s"
  depends_on                 = [google_project_service.required]
}

resource "google_pubsub_topic" "dead_letter" {
  name                       = "aivd-dead-letter"
  message_retention_duration = "1209600s"
  depends_on                 = [google_project_service.required]
}

resource "google_pubsub_subscription" "alert_dispatch" {
  name                 = "aivd-alert-dispatch"
  topic                = google_pubsub_topic.alerts.id
  ack_deadline_seconds = 60
  message_retention_duration = "604800s"

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 10
  }
}

resource "google_pubsub_subscription" "dead_letter_audit" {
  name                       = "aivd-dead-letter-audit"
  topic                      = google_pubsub_topic.dead_letter.id
  message_retention_duration = "1209600s"
}

resource "google_pubsub_topic_iam_member" "pubsub_dead_letter_publisher" {
  topic  = google_pubsub_topic.dead_letter.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription_iam_member" "pubsub_dead_letter_subscriber" {
  subscription = google_pubsub_subscription.alert_dispatch.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id                 = "aivd_analytics"
  friendly_name              = "AI Vision Director long-term analytics"
  location                   = var.region
  delete_contents_on_destroy = false
  default_partition_expiration_ms = 31536000000

  labels = {
    system = "aivd"
    phase  = "6"
  }
  depends_on = [google_project_service.required]
}

resource "google_bigquery_table" "cloud_events" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "cloud_events"
  deletion_protection = true

  time_partitioning {
    type  = "DAY"
    field = "occurred_at"
  }
  clustering = ["organization_id", "event_type"]
  schema = jsonencode([
    { name = "event_id", type = "STRING", mode = "REQUIRED" },
    { name = "event_type", type = "STRING", mode = "REQUIRED" },
    { name = "occurred_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "organization_id", type = "STRING", mode = "REQUIRED" },
    { name = "actor_uid", type = "STRING", mode = "NULLABLE" },
    { name = "subject", type = "STRING", mode = "REQUIRED" },
    { name = "schema_version", type = "INTEGER", mode = "REQUIRED" },
    { name = "correlation_id", type = "STRING", mode = "NULLABLE" },
    { name = "data", type = "JSON", mode = "REQUIRED" },
  ])
}

resource "google_project_iam_member" "pubsub_bigquery_writer" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription" "telemetry_bigquery" {
  name  = "aivd-telemetry-bigquery"
  topic = google_pubsub_topic.telemetry.id

  bigquery_config {
    table            = "${var.project_id}.${google_bigquery_dataset.analytics.dataset_id}.${google_bigquery_table.cloud_events.table_id}"
    use_table_schema = true
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 10
  }
  depends_on = [google_project_iam_member.pubsub_bigquery_writer]
}

resource "google_pubsub_subscription" "benchmark_bigquery" {
  name  = "aivd-benchmark-bigquery"
  topic = google_pubsub_topic.benchmark.id

  bigquery_config {
    table            = "${var.project_id}.${google_bigquery_dataset.analytics.dataset_id}.${google_bigquery_table.cloud_events.table_id}"
    use_table_schema = true
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 10
  }
  depends_on = [google_project_iam_member.pubsub_bigquery_writer]
}

resource "google_pubsub_subscription" "alerts_bigquery" {
  name  = "aivd-alerts-bigquery"
  topic = google_pubsub_topic.alerts.id

  bigquery_config {
    table            = "${var.project_id}.${google_bigquery_dataset.analytics.dataset_id}.${google_bigquery_table.cloud_events.table_id}"
    use_table_schema = true
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 10
  }
  depends_on = [google_project_iam_member.pubsub_bigquery_writer]
}

resource "google_cloud_run_v2_job" "benchmark_cpu" {
  name                = "aivd-benchmark-cpu"
  location            = var.region
  deletion_protection = true

  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.runtime.email
      max_retries     = 0
      timeout         = "3600s"
      containers {
        image   = local.benchmark_image
        command = ["python3"]
        args    = ["-m", "autocamtracker.cloud.benchmark_worker"]
        env {
          name  = "AIVD_FIREBASE_PROJECT_ID"
          value = var.project_id
        }
        env {
          name = "AIVD_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }
        resources {
          limits = {
            cpu    = "2"
            memory = "4Gi"
          }
        }
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.postgres.connection_name]
        }
      }
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_job" "benchmark_gpu" {
  count               = var.enable_gpu_benchmark ? 1 : 0
  name                = "aivd-benchmark-gpu"
  location            = var.gpu_region
  deletion_protection = true

  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account                = google_service_account.runtime.email
      max_retries                    = 0
      timeout                        = "3600s"
      gpu_zonal_redundancy_disabled  = true
      node_selector {
        accelerator = "nvidia-l4"
      }
      containers {
        image   = local.benchmark_image
        command = ["python3"]
        args    = ["-m", "autocamtracker.cloud.benchmark_worker"]
        env {
          name  = "AIVD_FIREBASE_PROJECT_ID"
          value = var.project_id
        }
        env {
          name = "AIVD_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }
        resources {
          limits = {
            cpu              = "4"
            memory           = "16Gi"
            "nvidia.com/gpu" = "1"
          }
        }
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.postgres.connection_name]
        }
      }
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_billing_budget" "notifications" {
  billing_account = var.billing_account_id
  display_name    = "AI Vision Director US$1 notifications"

  budget_filter {
    projects = ["projects/${data.google_project.current.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = "1"
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.8
  }
  threshold_rules {
    threshold_percent = 1.0
  }

  all_updates_rule {
    pubsub_topic                     = google_pubsub_topic.billing.id
    schema_version                   = "1.0"
    monitoring_notification_channels = []
    disable_default_iam_recipients   = false
  }
}

resource "google_monitoring_alert_policy" "api_errors" {
  display_name = "AIVD Cloud Run API 5xx"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run API 5xx responses"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_revision\"",
        "resource.label.service_name=\"${local.api_service}\"",
        "metric.type=\"run.googleapis.com/request_count\"",
        "metric.label.response_code_class=\"5xx\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "60s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  notification_channels = var.alert_email == "" ? [] : [
    google_monitoring_notification_channel.email[0].name
  ]
}

resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email == "" ? 0 : 1
  display_name = "AIVD operations email"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "benchmark_failures" {
  display_name = "AIVD benchmark job failures"
  combiner     = "OR"
  conditions {
    display_name = "Cloud Run benchmark task failed"
    condition_matched_log {
      filter = join(" AND ", [
        "resource.type=\"cloud_run_job\"",
        "severity>=ERROR",
        "resource.labels.job_name=monitoring.regex.full_match(\"aivd-benchmark-(cpu|gpu)\")",
      ])
    }
  }
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }
  notification_channels = var.alert_email == "" ? [] : [
    google_monitoring_notification_channel.email[0].name
  ]
}
