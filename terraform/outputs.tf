output "dataset_id" {
  value = google_bigquery_dataset.iam.dataset_id
}

output "cloud_run_url" {
  value = google_cloud_run_v2_service.executor.uri
}

output "executor_service_account" {
  value = google_service_account.executor.email
}

output "management_scope" {
  value       = trimspace(var.organization_id) == "" ? "project-only" : "organization+project"
  description = "Scope selected by organization_id. Empty organization_id means project-only."
}

output "tool_project_id" {
  value       = var.tool_project_id
  description = "Project hosting this IAM management tool."
}

output "effective_managed_project_id" {
  value       = trimspace(var.managed_project_id) == "" ? var.tool_project_id : var.managed_project_id
  description = "Effective managed target project. Falls back to tool_project_id when empty."
}
