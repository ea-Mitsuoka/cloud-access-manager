provider "google" {
  project = var.tool_project_id
  region  = var.region
}

locals {
  organization_scope_enabled   = trimspace(var.organization_id) != ""
  effective_managed_project_id = trimspace(var.managed_project_id) != "" ? var.managed_project_id : var.tool_project_id

  labels = {
    system = "iam-access-management"
    owner  = "security"
    scope  = local.organization_scope_enabled ? "organization" : "project"
  }

  executor_project_roles = [
    "roles/resourcemanager.projectIamAdmin",
    "roles/cloudasset.viewer",
  ]

  executor_organization_roles = [
    "roles/resourcemanager.projectIamAdmin",
    "roles/browser",
    "roles/cloudasset.viewer",
    "roles/resourcemanager.folderAdmin",
  ]

  base_enabled_services = toset([
    "bigquery.googleapis.com",
    "cloudasset.googleapis.com",
    "cloudidentity.googleapis.com",
    "cloudscheduler.googleapis.com",
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
  ])
  conditional_enabled_services = toset(
    var.enable_vpc_sc ? ["accesscontextmanager.googleapis.com"] : []
  )
  all_enabled_services = setunion(local.base_enabled_services, local.conditional_enabled_services)
}

# プロジェクト番号を取得（VPC-SCの境界設定に必要）
data "google_project" "tool_project" {
  project_id = var.tool_project_id
}

resource "google_project_service" "services" {
  for_each = local.all_enabled_services

  project = var.tool_project_id
  service = each.value

  disable_dependent_services = false
  disable_on_destroy         = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_bigquery_dataset" "iam" {
  project    = var.tool_project_id
  dataset_id = var.dataset_id
  location   = var.region

  labels = local.labels

  depends_on = [google_project_service.services]
}

resource "google_bigquery_table" "iam_access_requests" {
  project    = var.tool_project_id
  dataset_id = google_bigquery_dataset.iam.dataset_id
  table_id   = "iam_access_requests"

  lifecycle {
    prevent_destroy = true
  }

  time_partitioning {
    type  = "DAY"
    field = "requested_at"
  }

  clustering = ["status", "principal_email", "role"]

  schema = jsonencode([
    { name = "request_id", type = "STRING", mode = "REQUIRED" },
    { name = "request_type", type = "STRING", mode = "REQUIRED" },
    { name = "principal_email", type = "STRING", mode = "REQUIRED" },
    { name = "resource_name", type = "STRING", mode = "REQUIRED" },
    { name = "role", type = "STRING", mode = "REQUIRED" },
    { name = "reason", type = "STRING", mode = "NULLABLE" },
    { name = "expires_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "requester_email", type = "STRING", mode = "REQUIRED" },
    { name = "approver_email", type = "STRING", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "requested_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "approved_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "ticket_ref", type = "STRING", mode = "NULLABLE" },
    { name = "created_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "updated_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "iam_access_change_log" {
  project    = var.tool_project_id
  dataset_id = google_bigquery_dataset.iam.dataset_id
  table_id   = "iam_access_change_log"

  lifecycle {
    prevent_destroy = true
  }

  time_partitioning {
    type  = "DAY"
    field = "executed_at"
  }

  clustering = ["request_id", "result"]

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "request_id", type = "STRING", mode = "REQUIRED" },
    { name = "action", type = "STRING", mode = "REQUIRED" },
    { name = "target", type = "STRING", mode = "REQUIRED" },
    { name = "before_hash", type = "STRING", mode = "NULLABLE" },
    { name = "after_hash", type = "STRING", mode = "NULLABLE" },
    { name = "result", type = "STRING", mode = "REQUIRED" },
    { name = "error_code", type = "STRING", mode = "NULLABLE" },
    { name = "error_message", type = "STRING", mode = "NULLABLE" },
    { name = "executed_by", type = "STRING", mode = "NULLABLE" },
    { name = "executed_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "details", type = "JSON", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "iam_policy_bindings_raw_history" {
  project    = var.tool_project_id
  dataset_id = google_bigquery_dataset.iam.dataset_id
  table_id   = "iam_policy_bindings_raw_history"

  lifecycle {
    prevent_destroy = true
  }

  time_partitioning {
    type  = "DAY"
    field = "assessment_timestamp"
  }

  clustering = ["resource_type", "principal_email", "role"]

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "assessment_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "scope", type = "STRING", mode = "NULLABLE" },
    { name = "resource_type", type = "STRING", mode = "NULLABLE" },
    { name = "resource_name", type = "STRING", mode = "NULLABLE" },
    { name = "principal_type", type = "STRING", mode = "NULLABLE" },
    { name = "principal_email", type = "STRING", mode = "NULLABLE" },
    { name = "role", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "iam_reconciliation_issues" {
  project    = var.tool_project_id
  dataset_id = google_bigquery_dataset.iam.dataset_id
  table_id   = "iam_reconciliation_issues"

  lifecycle {
    prevent_destroy = true
  }

  time_partitioning {
    type  = "DAY"
    field = "detected_at"
  }

  clustering = ["issue_type", "status", "severity"]

  schema = jsonencode([
    { name = "issue_id", type = "STRING", mode = "REQUIRED" },
    { name = "issue_type", type = "STRING", mode = "REQUIRED" },
    { name = "request_id", type = "STRING", mode = "NULLABLE" },
    { name = "principal_email", type = "STRING", mode = "NULLABLE" },
    { name = "resource_name", type = "STRING", mode = "NULLABLE" },
    { name = "role", type = "STRING", mode = "NULLABLE" },
    { name = "detected_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "severity", type = "STRING", mode = "REQUIRED" },
    { name = "status", type = "STRING", mode = "REQUIRED" },
    { name = "details", type = "JSON", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "iam_pipeline_job_reports" {
  project    = var.tool_project_id
  dataset_id = google_bigquery_dataset.iam.dataset_id
  table_id   = "iam_pipeline_job_reports"

  lifecycle {
    prevent_destroy = true
  }

  time_partitioning {
    type  = "DAY"
    field = "occurred_at"
  }

  clustering = ["job_type", "result"]

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED" },
    { name = "job_type", type = "STRING", mode = "REQUIRED" },
    { name = "result", type = "STRING", mode = "REQUIRED" },
    { name = "error_code", type = "STRING", mode = "NULLABLE" },
    { name = "error_message", type = "STRING", mode = "NULLABLE" },
    { name = "hint", type = "STRING", mode = "NULLABLE" },
    { name = "counts", type = "JSON", mode = "NULLABLE" },
    { name = "details", type = "JSON", mode = "NULLABLE" },
    { name = "occurred_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_service_account" "executor" {
  account_id   = "iam-access-executor"
  display_name = "IAM Access Executor"
}

resource "google_service_account" "scheduler_invoker" {
  account_id   = "iam-scheduler-invoker"
  display_name = "IAM Scheduler Invoker"
}

resource "google_bigquery_dataset_iam_member" "executor_bigquery_data_editor" {
  project    = var.tool_project_id
  dataset_id = google_bigquery_dataset.iam.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.executor.email}"
}

resource "google_project_iam_member" "executor_bigquery_job_user" {
  project = var.tool_project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.executor.email}"
}

# Project-only scope roles for executor SA
resource "google_project_iam_member" "executor_managed_project_roles" {
  for_each = toset(local.executor_project_roles)
  count    = local.organization_scope_enabled ? 0 : 1
  project  = local.effective_managed_project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.executor.email}"
}

# Organization scope roles for executor SA
resource "google_organization_iam_member" "executor_managed_organization_roles" {
  for_each = toset(local.executor_organization_roles)
  count    = local.organization_scope_enabled ? 1 : 0
  org_id   = var.organization_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.executor.email}"
}

resource "google_secret_manager_secret_iam_member" "executor_secret_accessor" {
  project   = var.tool_project_id
  secret_id = var.webhook_secret_name
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.executor.email}"
}

resource "google_cloud_run_v2_service" "executor" {
  name     = var.cloud_run_service_name
  location = var.region
  # VPC-SC有効時は内部トラフィック＋LB経由のみに制限
  ingress = var.enable_vpc_sc ? "INGRESS_TRAFFIC_INTERNAL_AND_CLOUD_LOAD_BALANCING" : "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.executor.email
    timeout         = "900s"

    containers {
      image = var.cloud_run_image

      env {
        name  = "BQ_PROJECT_ID"
        value = var.tool_project_id
      }
      env {
        name  = "BQ_DATASET_ID"
        value = var.dataset_id
      }
      env {
        name  = "MGMT_TARGET_PROJECT_ID"
        value = local.effective_managed_project_id
      }
      env {
        name  = "MGMT_TARGET_ORGANIZATION_ID"
        value = var.organization_id
      }
      env {
        name  = "WORKSPACE_CUSTOMER_ID"
        value = var.workspace_customer_id
      }
      env {
        name  = "EXECUTOR_IDENTITY"
        value = google_service_account.executor.email
      }
      env {
        name  = "SCHEDULER_INVOKER_EMAIL"
        value = google_service_account.scheduler_invoker.email
      }
      env {
        name = "WEBHOOK_SHARED_SECRET"
        value_source {
          secret_key_ref {
            secret  = var.webhook_secret_name
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.services,
    google_bigquery_dataset_iam_member.executor_bigquery_data_editor,
    google_project_iam_member.executor_bigquery_job_user,
    google_secret_manager_secret_iam_member.executor_secret_accessor,
    google_project_iam_member.executor_managed_project_roles,
    google_organization_iam_member.executor_managed_organization_roles,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "scheduler_run_invoker" {
  project  = var.tool_project_id
  location = var.region
  name     = google_cloud_run_v2_service.executor.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "resource_inventory_daily" {
  name      = "iam-resource-inventory-daily"
  project   = var.tool_project_id
  region    = var.region
  schedule  = var.resource_collection_schedule
  time_zone = var.scheduler_time_zone

  # 一過性のエラーに備えて最大3回まで自動リトライ
  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${google_cloud_run_v2_service.executor.uri}/collect/resources"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = google_cloud_run_v2_service.executor.uri
    }
  }

  depends_on = [
    google_project_service.services,
    google_cloud_run_v2_service_iam_member.scheduler_run_invoker,
  ]
}

resource "google_cloud_scheduler_job" "group_collection_daily" {
  name      = "iam-group-collection-daily"
  project   = var.tool_project_id
  region    = var.region
  schedule  = var.group_collection_schedule
  time_zone = var.scheduler_time_zone

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${google_cloud_run_v2_service.executor.uri}/collect/groups"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = google_cloud_run_v2_service.executor.uri
    }
  }

  depends_on = [
    google_project_service.services,
    google_cloud_run_v2_service_iam_member.scheduler_run_invoker,
  ]
}

resource "google_cloud_scheduler_job" "reconciliation_daily" {
  name      = "iam-reconciliation-daily"
  project   = var.tool_project_id
  region    = var.region
  schedule  = var.reconciliation_schedule
  time_zone = var.scheduler_time_zone

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${google_cloud_run_v2_service.executor.uri}/reconcile"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = google_cloud_run_v2_service.executor.uri
    }
  }

  depends_on = [
    google_project_service.services,
    google_cloud_run_v2_service_iam_member.scheduler_run_invoker,
  ]
}

resource "google_cloud_scheduler_job" "revoke_expired_permissions_daily" {
  name      = "iam-revoke-expired-permissions-daily"
  project   = var.tool_project_id
  region    = var.region
  schedule  = var.revoke_expired_permissions_schedule
  time_zone = var.scheduler_time_zone

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${google_cloud_run_v2_service.executor.uri}/revoke_expired_permissions"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = google_cloud_run_v2_service.executor.uri
    }
  }

  depends_on = [
    google_project_service.services,
    google_cloud_run_v2_service_iam_member.scheduler_run_invoker,
  ]
}

resource "google_cloud_scheduler_job" "iam_bindings_history_update_daily" {
  name      = "iam-bindings-history-update-daily"
  project   = var.tool_project_id
  region    = var.region
  schedule  = var.iam_bindings_history_update_schedule
  time_zone = var.scheduler_time_zone

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${google_cloud_run_v2_service.executor.uri}/jobs/update-iam-bindings-history"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = google_cloud_run_v2_service.executor.uri
    }
  }

  depends_on = [
    google_project_service.services,
    google_cloud_run_v2_service_iam_member.scheduler_run_invoker,
  ]
}

# --- VPC Service Controls (Optional) ---
resource "google_access_context_manager_service_perimeter" "tool_perimeter" {
  count  = var.enable_vpc_sc ? 1 : 0
  parent = var.access_policy_name
  name   = "${var.access_policy_name}/servicePerimeters/iam_access_manager_perimeter"
  title  = "iam-access-manager-perimeter"

  status {
    restricted_services = [
      "run.googleapis.com",
      "bigquery.googleapis.com",
      "secretmanager.googleapis.com",
      "cloudresourcemanager.googleapis.com",
      "cloudasset.googleapis.com",
      "cloudidentity.googleapis.com"
    ]
    resources = ["projects/${data.google_project.tool_project.number}"]
  }
}

# --- Monitoring Notification Channels & Alerting ---
resource "google_monitoring_notification_channel" "alert_email" {
  count        = trimspace(var.alert_notification_email) != "" ? 1 : 0
  project      = var.tool_project_id
  display_name = "IAM Access Manager - Alert Email"
  type         = "email"
  labels = {
    email_address = var.alert_notification_email
  }
}

resource "google_monitoring_notification_channel" "alert_webhook" {
  count        = trimspace(var.alert_notification_webhook_url) != "" ? 1 : 0
  project      = var.tool_project_id
  display_name = "IAM Access Manager - Alert Webhook"
  type         = "webhook_tokenauth"
  labels = {
    url = var.alert_notification_webhook_url
  }
}

resource "google_monitoring_alert_policy" "cloud_run_errors" {
  # どちらか1つでも設定されていればアラートポリシーを作成
  count        = (trimspace(var.alert_notification_email) != "" || trimspace(var.alert_notification_webhook_url) != "") ? 1 : 0
  project      = var.tool_project_id
  display_name = "IAM Access Manager: Error Detected"
  combiner     = "OR"
  conditions {
    display_name = "Cloud Run App Errors"
    condition_matched_log {
      # Cloud Run サービス内で ERROR 以上のログが出た場合に検知
      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.executor.name}\" AND severity>=\"ERROR\""
    }
  }
  notification_channels = compact([
    length(google_monitoring_notification_channel.alert_email) > 0 ? google_monitoring_notification_channel.alert_email[0].name : "",
    length(google_monitoring_notification_channel.alert_webhook) > 0 ? google_monitoring_notification_channel.alert_webhook[0].name : ""
  ])
}

resource "google_monitoring_alert_policy" "break_glass_alert" {
  count        = (trimspace(var.alert_notification_email) != "" || trimspace(var.alert_notification_webhook_url) != "") ? 1 : 0
  project      = var.tool_project_id
  display_name = "IAM Access Manager: Break-glass (Emergency) Access Detected"
  combiner     = "OR"
  conditions {
    display_name = "Break-glass Execution Logs"
    condition_matched_log {
      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${google_cloud_run_v2_service.executor.name}\" AND textPayload:\"[BREAK-GLASS]\""
    }
  }
  notification_channels = compact([
    length(google_monitoring_notification_channel.alert_email) > 0 ? google_monitoring_notification_channel.alert_email[0].name : "",
    length(google_monitoring_notification_channel.alert_webhook) > 0 ? google_monitoring_notification_channel.alert_webhook[0].name : ""
  ])
}
