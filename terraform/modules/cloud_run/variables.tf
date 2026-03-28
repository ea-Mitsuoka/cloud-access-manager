variable "service_name" {
  type        = string
  description = "Cloud Run service name"
}

variable "region" {
  type        = string
  description = "Primary region"
}

variable "enable_vpc_sc" {
  type        = bool
  description = "Enable VPC Service Controls perimeter for the tool project"
}

variable "executor_service_account_email" {
  type        = string
  description = "Email of the executor service account"
}

variable "image" {
  type        = string
  description = "Container image URL for Cloud Run service"
}

variable "tool_project_id" {
  type        = string
  description = "GCP project ID for deploying this IAM management tool"
}

variable "dataset_id" {
  type        = string
  description = "BigQuery dataset ID"
}

variable "effective_managed_project_id" {
  type        = string
  description = "Effective managed target project. Falls back to tool_project_id when empty."
}

variable "organization_id" {
  type        = string
  description = "GCP organization numeric ID (optional). Empty means project-only scope."
}

variable "workspace_customer_id" {
  type        = string
  description = "Workspace customer ID for Cloud Identity groups search"
}

variable "scheduler_invoker_service_account_email" {
  type        = string
  description = "Email of the scheduler invoker service account"
}

variable "webhook_secret_name" {
  type        = string
  description = "Secret Manager secret name for webhook token"
}
