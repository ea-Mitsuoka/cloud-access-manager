resource "google_cloud_scheduler_job" "resource_inventory_daily" {
  name             = "iam-resource-inventory-daily"
  project          = var.tool_project_id
  region           = var.region
  schedule         = var.resource_collection_schedule
  time_zone        = var.scheduler_time_zone
  attempt_deadline = "900s"

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${var.cloud_run_uri}/collect/resources"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = var.scheduler_invoker_service_account_email
      audience              = var.cloud_run_uri
    }
  }
}

resource "google_cloud_scheduler_job" "group_collection_daily" {
  name             = "iam-group-collection-daily"
  project          = var.tool_project_id
  region           = var.region
  schedule         = var.group_collection_schedule
  time_zone        = var.scheduler_time_zone
  attempt_deadline = "900s"

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${var.cloud_run_uri}/collect/groups"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = var.scheduler_invoker_service_account_email
      audience              = var.cloud_run_uri
    }
  }
}

resource "google_cloud_scheduler_job" "reconciliation_daily" {
  name             = "iam-reconciliation-daily"
  project          = var.tool_project_id
  region           = var.region
  schedule         = var.reconciliation_schedule
  time_zone        = var.scheduler_time_zone
  attempt_deadline = "900s"

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${var.cloud_run_uri}/reconcile"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = var.scheduler_invoker_service_account_email
      audience              = var.cloud_run_uri
    }
  }
}

resource "google_cloud_scheduler_job" "revoke_expired_permissions_daily" {
  name             = "iam-revoke-expired-permissions-daily"
  project          = var.tool_project_id
  region           = var.region
  schedule         = var.revoke_expired_permissions_schedule
  time_zone        = var.scheduler_time_zone
  attempt_deadline = "900s"

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${var.cloud_run_uri}/revoke_expired_permissions"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = var.scheduler_invoker_service_account_email
      audience              = var.cloud_run_uri
    }
  }
}

resource "google_cloud_scheduler_job" "iam_bindings_history_update_daily" {
  name             = "iam-bindings-history-update-daily"
  project          = var.tool_project_id
  region           = var.region
  schedule         = var.iam_bindings_history_update_schedule
  time_zone        = var.scheduler_time_zone
  attempt_deadline = "900s"

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${var.cloud_run_uri}/jobs/update-iam-bindings-history"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = var.scheduler_invoker_service_account_email
      audience              = var.cloud_run_uri
    }
  }
}

resource "google_cloud_scheduler_job" "iam_policy_collection_daily" {
  name             = "iam-policy-collection-daily"
  project          = var.tool_project_id
  region           = var.region
  schedule         = var.iam_policy_collection_schedule
  time_zone        = var.scheduler_time_zone
  attempt_deadline = "900s"

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${var.cloud_run_uri}/collect/iam-policies"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = var.scheduler_invoker_service_account_email
      audience              = var.cloud_run_uri
    }
  }
}

resource "google_cloud_scheduler_job" "iam_role_discovery_daily" {
  name             = "iam-role-discovery-daily"
  project          = var.tool_project_id
  region           = var.region
  schedule         = var.iam_role_discovery_schedule
  time_zone        = var.scheduler_time_zone
  attempt_deadline = "900s"

  retry_config {
    retry_count = 3
  }

  http_target {
    uri         = "${var.cloud_run_uri}/jobs/discover-iam-roles"
    http_method = "POST"
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode("{}")

    oidc_token {
      service_account_email = var.scheduler_invoker_service_account_email
      audience              = var.cloud_run_uri
    }
  }
}
