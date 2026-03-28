output "resource_inventory_scheduler_job_name" {
  value       = google_cloud_scheduler_job.resource_inventory_daily.name
  description = "Cloud Scheduler job name for daily resource inventory collection."
}

output "group_collection_scheduler_job_name" {
  value       = google_cloud_scheduler_job.group_collection_daily.name
  description = "Cloud Scheduler job name for daily Google group collection."
}

output "reconciliation_scheduler_job_name" {
  value       = google_cloud_scheduler_job.reconciliation_daily.name
  description = "Cloud Scheduler job name for daily reconciliation."
}

output "revoke_expired_permissions_scheduler_job_name" {
  value       = google_cloud_scheduler_job.revoke_expired_permissions_daily.name
  description = "Cloud Scheduler job name for daily revocation of expired permissions."
}

output "iam_bindings_history_update_scheduler_job_name" {
  value       = google_cloud_scheduler_job.iam_bindings_history_update_daily.name
  description = "Cloud Scheduler job name for daily update of IAM bindings history."
}
