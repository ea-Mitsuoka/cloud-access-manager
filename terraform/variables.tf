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

variable "webhook_shared_secret" {
  type        = string
  description = "Shared secret for X-Webhook-Token"
  sensitive   = true
}
