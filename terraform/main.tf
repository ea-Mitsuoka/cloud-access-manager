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
}

resource "google_project_service" "services" {
  for_each = toset([
    "bigquery.googleapis.com",
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
  ])

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

resource "google_bigquery_table" "iam_policy_permissions_history" {
  project    = var.tool_project_id
  dataset_id = google_bigquery_dataset.iam.dataset_id
  table_id   = "iam_policy_permissions_history"

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

resource "google_service_account" "executor" {
  account_id   = "iam-access-executor"
  display_name = "IAM Access Executor"
}

resource "google_project_iam_member" "executor_bigquery_editor" {
  project = var.tool_project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.executor.email}"
}

resource "google_cloud_run_v2_service" "executor" {
  name     = var.cloud_run_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.executor.email

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
        name  = "EXECUTOR_IDENTITY"
        value = google_service_account.executor.email
      }
      env {
        name  = "WEBHOOK_SHARED_SECRET"
        value = var.webhook_shared_secret
      }
    }
  }

  depends_on = [
    google_project_service.services,
    google_project_iam_member.executor_bigquery_editor,
  ]
}
