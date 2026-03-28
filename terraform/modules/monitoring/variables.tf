variable "tool_project_id" {
  type        = string
  description = "GCP project ID for deploying this IAM management tool"
}

variable "alert_notification_email" {
  type        = string
  description = "Email address for anomaly alerts (optional)"
}

variable "alert_notification_webhook_url" {
  type        = string
  description = "Webhook URL for anomaly alerts like Slack or Google Chat (optional)"
}

variable "cloud_run_service_name" {
  type        = string
  description = "Cloud Run service name"
}
