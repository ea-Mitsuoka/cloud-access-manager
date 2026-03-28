resource "google_cloud_run_v2_service" "executor" {
  name     = var.service_name
  location = var.region
  ingress  = var.enable_vpc_sc ? "INGRESS_TRAFFIC_INTERNAL_AND_CLOUD_LOAD_BALANCING" : "INGRESS_TRAFFIC_ALL"

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
    }
  }
}
