resource "google_bigquery_dataset" "iam" {
  project    = var.tool_project_id
  dataset_id = var.dataset_id
  location   = var.region

  labels = var.labels
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
    {
      name = "counts",
      type = "RECORD",
      mode = "NULLABLE",
      fields = [
        { name = "processed", type = "INT64", mode = "NULLABLE" },
        { name = "added", type = "INT64", mode = "NULLABLE" },
        { name = "removed", type = "INT64", mode = "NULLABLE" },
        { name = "failed", type = "INT64", mode = "NULLABLE" }
      ]
    },
    {
      name = "details",
      type = "RECORD",
      mode = "NULLABLE",
      fields = [
        { name = "info", type = "STRING", mode = "NULLABLE" },
        { name = "raw_response", type = "STRING", mode = "NULLABLE" }
      ]
    },
    { name = "occurred_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "iam_policy_permissions" {
  project    = var.tool_project_id
  dataset_id = google_bigquery_dataset.iam.dataset_id
  table_id   = "iam_policy_permissions"

  deletion_protection = false

  lifecycle {
    prevent_destroy = false
  }
  time_partitioning {
    type  = "DAY"
    field = "assessment_timestamp"
  }

  clustering = ["resource_type", "principal_email", "role"]

  schema = jsonencode([
    { name = "execution_id", type = "STRING", mode = "REQUIRED", description = "1回の評価実行を一意に識別するUUID" },
    { name = "assessment_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "scope", type = "STRING", mode = "REQUIRED" },
    { name = "resource_type", type = "STRING", mode = "REQUIRED", description = "リソースの種類 (例: IAM_POLICY_NAME)" },
    { name = "resource_name", type = "STRING", mode = "REQUIRED", description = "具体的なリソース名" },
    { name = "principal_type", type = "STRING", mode = "NULLABLE" },
    { name = "principal_email", type = "STRING", mode = "NULLABLE" },
    { name = "role", type = "STRING", mode = "REQUIRED" },
  ])
}
