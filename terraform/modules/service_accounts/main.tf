resource "google_service_account" "executor" {
  project      = var.tool_project_id
  account_id   = "iam-access-executor"
  display_name = "IAM Access Executor"
}

resource "google_service_account" "scheduler_invoker" {
  project      = var.tool_project_id
  account_id   = "iam-scheduler-invoker"
  display_name = "IAM Scheduler Invoker"
}

resource "google_service_account" "gas_invoker" {
  project      = var.tool_project_id
  account_id   = "iam-gas-invoker"
  display_name = "IAM GAS Invoker"
}

resource "google_service_account_iam_member" "gas_trigger_owner_token_creator" {
  count              = trimspace(var.gas_trigger_owner_email) != "" ? 1 : 0
  service_account_id = google_service_account.gas_invoker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "user:${var.gas_trigger_owner_email}"
}
