output "dataset_id" {
  value = module.bigquery.dataset_id
}

output "cloud_run_url" {
  value = module.cloud_run.uri
}

output "executor_service_account" {
  value = module.service_accounts.executor_service_account_email
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
  value       = local.effective_managed_project_id
  description = "Effective managed target project. Falls back to tool_project_id when empty."
}

output "scheduler_invoker_service_account" {
  value       = module.service_accounts.scheduler_invoker_service_account_email
  description = "Service account used by Cloud Scheduler OIDC calls."
}

output "resource_inventory_scheduler_job" {
  value       = module.scheduler.resource_inventory_scheduler_job_name
  description = "Cloud Scheduler job name for daily resource inventory collection."
}

output "principal_collection_scheduler_job" {
  value       = module.scheduler.principal_collection_scheduler_job_name
  description = "Cloud Scheduler job name for daily principal collection."
}

output "reconciliation_scheduler_job" {
  value       = module.scheduler.reconciliation_scheduler_job_name
  description = "Cloud Scheduler job name for daily reconciliation."
}

output "revoke_expired_permissions_scheduler_job" {
  value       = module.scheduler.revoke_expired_permissions_scheduler_job_name
  description = "Cloud Scheduler job name for daily revocation of expired permissions."
}

output "iam_bindings_history_update_scheduler_job" {
  value       = module.scheduler.iam_bindings_history_update_scheduler_job_name
  description = "Cloud Scheduler job name for daily update of IAM bindings history."
}
