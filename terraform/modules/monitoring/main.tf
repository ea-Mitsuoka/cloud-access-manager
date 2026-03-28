resource "google_monitoring_notification_channel" "alert_email" {
  count        = trimspace(var.alert_notification_email) != "" ? 1 : 0
  project      = var.tool_project_id
  display_name = "IAM Access Manager - Alert Email"
  type         = "email"
  labels = {
    email_address = var.alert_notification_email
  }
}

resource "google_monitoring_notification_channel" "alert_webhook" {
  count        = trimspace(var.alert_notification_webhook_url) != "" ? 1 : 0
  project      = var.tool_project_id
  display_name = "IAM Access Manager - Alert Webhook"
  type         = "webhook_tokenauth"
  labels = {
    url = var.alert_notification_webhook_url
  }
}

resource "google_monitoring_alert_policy" "cloud_run_errors" {
  # どちらか1つでも設定されていればアラートポリシーを作成
  count        = (trimspace(var.alert_notification_email) != "" || trimspace(var.alert_notification_webhook_url) != "") ? 1 : 0
  project      = var.tool_project_id
  display_name = "IAM Access Manager: Error Detected"
  combiner     = "OR"
  conditions {
    display_name = "Cloud Run App Errors"
    condition_matched_log {
      # Cloud Run サービス内で ERROR 以上のログが出た場合に検知
      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.cloud_run_service_name}\" AND severity>=\"ERROR\""
    }
  }
  notification_channels = compact([
    length(google_monitoring_notification_channel.alert_email) > 0 ? google_monitoring_notification_channel.alert_email[0].name : "",
    length(google_monitoring_notification_channel.alert_webhook) > 0 ? google_monitoring_notification_channel.alert_webhook[0].name : ""
  ])
}

resource "google_monitoring_alert_policy" "break_glass_alert" {
  count        = (trimspace(var.alert_notification_email) != "" || trimspace(var.alert_notification_webhook_url) != "") ? 1 : 0
  project      = var.tool_project_id
  display_name = "IAM Access Manager: Break-glass (Emergency) Access Detected"
  combiner     = "OR"
  conditions {
    display_name = "Break-glass Execution Logs"
    condition_matched_log {
      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.cloud_run_service_name}\" AND textPayload:\"[BREAK-GLASS]\""
    }
  }
  notification_channels = compact([
    length(google_monitoring_notification_channel.alert_email) > 0 ? google_monitoring_notification_channel.alert_email[0].name : "",
    length(google_monitoring_notification_channel.alert_webhook) > 0 ? google_monitoring_notification_channel.alert_webhook[0].name : ""
  ])
}

resource "google_monitoring_alert_policy" "reconciliation_alert" {
  count        = (trimspace(var.alert_notification_email) != "" || trimspace(var.alert_notification_webhook_url) != "") ? 1 : 0
  project      = var.tool_project_id
  display_name = "IAM Access Manager: Reconciliation Issue Detected"
  combiner     = "OR"
  conditions {
    display_name = "Reconciliation Issue Logs"
    condition_matched_log {
      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.cloud_run_service_name}\" AND textPayload:\"[RECONCILIATION_ISSUE_DETECTED]\""
    }
  }
  notification_channels = compact([
    length(google_monitoring_notification_channel.alert_email) > 0 ? google_monitoring_notification_channel.alert_email[0].name : "",
    length(google_monitoring_notification_channel.alert_webhook) > 0 ? google_monitoring_notification_channel.alert_webhook[0].name : ""
  ])
}