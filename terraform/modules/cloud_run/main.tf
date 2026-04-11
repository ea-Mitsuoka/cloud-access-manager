data "google_project" "tool_project" {
  project_id = var.tool_project_id
}

resource "google_cloud_run_v2_service" "executor" {
  provider            = google-beta
  name                = var.service_name
  location            = var.region
  ingress             = var.enable_vpc_sc ? "INGRESS_TRAFFIC_INTERNAL_AND_CLOUD_LOAD_BALANCING" : "INGRESS_TRAFFIC_ALL"
  launch_stage        = "BETA"
  deletion_protection = false
  iap_enabled         = var.enable_iap

  template {
    service_account = var.executor_service_account_email
    timeout         = "900s"

    containers {
      image = var.image

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
        value = var.effective_managed_project_id
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
        value = var.executor_service_account_email
      }
      env {
        name  = "SCHEDULER_INVOKER_EMAIL"
        value = var.scheduler_invoker_service_account_email
      }
      env {
        name  = "GAS_INVOKER_EMAIL"
        value = var.gas_invoker_service_account_email
      }
      env {
        name  = "IAP_OAUTH_CLIENT_ID"
        value = var.iap_oauth_client_id
      }
    }
  }
}

resource "google_iap_web_cloud_run_service_iam_member" "iap_accessors" {
  for_each               = var.enable_iap ? toset(var.iap_allowed_principals) : toset([])
  project                = var.tool_project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.executor.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.value
}

resource "google_cloud_run_v2_service_iam_member" "iap_service_agent_invoker" {
  count    = var.enable_iap ? 1 : 0
  project  = var.tool_project_id
  location = var.region
  name     = google_cloud_run_v2_service.executor.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${data.google_project.tool_project.number}@gcp-sa-iap.iam.gserviceaccount.com"
}
