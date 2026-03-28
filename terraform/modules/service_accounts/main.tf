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
