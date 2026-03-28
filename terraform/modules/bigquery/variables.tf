variable "tool_project_id" {
  type        = string
  description = "GCP project ID for deploying this IAM management tool"
}

variable "dataset_id" {
  type        = string
  description = "BigQuery dataset ID"
}

variable "region" {
  type        = string
  description = "Primary region"
}

variable "labels" {
  type        = map(string)
  description = "Labels to apply to the dataset"
  default     = {}
}
