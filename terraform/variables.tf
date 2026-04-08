variable "tool_project_id" {
  type        = string
  description = "GCP project ID for deploying this IAM management tool"
}

variable "managed_project_id" {
  type        = string
  description = "Managed target project ID (optional). Empty means using tool_project_id."
  default     = ""
}

variable "organization_id" {
  type        = string
  description = "GCP organization numeric ID (optional). Empty means project-only scope."
  default     = ""

  validation {
    condition     = var.organization_id == "" || can(regex("^[0-9]+$", var.organization_id))
    error_message = "organization_id must be empty or a numeric string."
  }
}

variable "region" {
  type        = string
  description = "Primary region"
  default     = "asia-northeast1"
}

variable "dataset_id" {
  type        = string
  description = "BigQuery dataset ID"
  default     = "iam_access_mgmt"
}

variable "cloud_run_service_name" {
  type        = string
  description = "Cloud Run service name"
  default     = "iam-access-executor"
}

variable "cloud_run_image" {
  type        = string
  description = "Container image URL for Cloud Run service"
}

variable "gas_trigger_owner_email" {
  type        = string
  description = "Email of the user who owns the GAS triggers (to grant Service Account Token Creator role)"
  default     = ""
}

variable "workspace_customer_id" {
  type        = string
  description = "Workspace customer ID for Cloud Identity groups search (e.g. my_customer or C0123abc)"
  default     = "my_customer"
}

variable "enable_vpc_sc" {
  type        = bool
  description = "Enable VPC Service Controls perimeter for the tool project (Requires Organization Admin & Access Context Manager roles)"
  default     = false
}

variable "access_policy_name" {
  type        = string
  description = "Access Policy name (e.g. accessPolicies/123456789012). Required if enable_vpc_sc is true."
  default     = ""
}

variable "resource_collection_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /collect/resources"
  default     = "0 2 * * *"
}

variable "group_collection_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /collect/groups"
  default     = "30 2 * * *"
}

variable "reconciliation_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /reconcile"
  default     = "0 4 * * *" # Daily at 04:00 AM
}

variable "revoke_expired_permissions_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /revoke_expired_permissions"
  default     = "0 1 * * *" # Daily at 01:00 AM
}

variable "iam_bindings_history_update_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /jobs/update-iam-bindings-history"
  default     = "30 3 * * *" # Daily at 03:30 AM
}

variable "scheduler_time_zone" {
  type        = string
  description = "Time zone for Cloud Scheduler jobs"
  default     = "Asia/Tokyo"
}

variable "alert_notification_email" {
  type        = string
  description = "Email address for anomaly alerts (optional)"
  default     = ""
}

variable "alert_notification_webhook_url" {
  type        = string
  description = "Webhook URL for anomaly alerts like Slack or Google Chat (optional)"
  default     = ""
}

variable "iam_policy_collection_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /collect/iam-policies"
  default     = "15 2 * * *"
}

variable "iam_role_discovery_schedule" {
  type        = string
  description = "Cloud Scheduler cron for /jobs/discover-iam-roles"
  default     = "30 4 * * *"
}
