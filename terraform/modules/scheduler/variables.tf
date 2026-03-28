variable "tool_project_id" {
  type        = string
  description = "GCP project ID for deploying this IAM management tool"
}

variable "region" {
  type        = string
  description = "Primary region"
}

variable "cloud_run_uri" {
  type        = string
  description = "The URI of the Cloud Run service"
}

variable "scheduler_invoker_service_account_email" {
  type        = string
  description = "The email of the scheduler invoker service account"
}

variable "resource_collection_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /collect/resources"
}

variable "group_collection_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /collect/groups"
}

variable "reconciliation_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /reconcile"
}

variable "revoke_expired_permissions_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /revoke_expired_permissions"
}

variable "iam_bindings_history_update_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /jobs/update-iam-bindings-history"
}

variable "scheduler_time_zone" {
  type        = string
  description = "Time zone for Cloud Scheduler jobs"
}

variable "iam_policy_collection_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /collect/iam-policies"
}
