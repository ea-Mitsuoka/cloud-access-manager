provider "google" {
  project = var.tool_project_id
  region  = var.region
}

locals {
  organization_scope_enabled   = trimspace(var.organization_id) != ""
  effective_managed_project_id = trimspace(var.managed_project_id) != "" ? var.managed_project_id : var.tool_project_id

  labels = {
    system = "iam-access-management"
    owner  = "security"
    scope  = local.organization_scope_enabled ? "organization" : "project"
  }

  executor_project_roles = [
    "roles/resourcemanager.projectIamAdmin",
    "roles/cloudasset.viewer",
  ]

  executor_organization_roles = [
    "roles/browser",
    "roles/cloudasset.viewer",
    "roles/resourcemanager.folderAdmin",
    "roles/resourcemanager.projectIamAdmin",
  ]

  base_enabled_services = toset([
    "bigquery.googleapis.com",
    "cloudasset.googleapis.com",
    "cloudidentity.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudscheduler.googleapis.com",
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
  ])
  conditional_enabled_services = toset(
    var.enable_vpc_sc ? ["accesscontextmanager.googleapis.com"] : []
  )
  all_enabled_services = setunion(local.base_enabled_services, local.conditional_enabled_services)
}

# プロジェクト番号を取得（VPC-SCの境界設定に必要）
data "google_project" "tool_project" {
  project_id = var.tool_project_id
}

resource "google_project_service" "services" {
  for_each = local.all_enabled_services

  project = var.tool_project_id
  service = each.value

  disable_dependent_services = false
  disable_on_destroy         = false

  lifecycle {
    prevent_destroy = true
  }
}

module "bigquery" {
  source          = "./modules/bigquery"
  tool_project_id = var.tool_project_id
  dataset_id      = var.dataset_id
  region          = var.region
  labels          = local.labels
  depends_on      = [google_project_service.services]
}

module "service_accounts" {
  source                  = "./modules/service_accounts"
  tool_project_id         = var.tool_project_id
  gas_trigger_owner_email = var.gas_trigger_owner_email
}

resource "google_bigquery_dataset_iam_member" "executor_bigquery_data_editor" {
  project    = var.tool_project_id
  dataset_id = module.bigquery.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${module.service_accounts.executor_service_account_email}"
}

resource "google_project_iam_member" "executor_bigquery_job_user" {
  project = var.tool_project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${module.service_accounts.executor_service_account_email}"
}

# Project-only scope roles for executor SA
resource "google_project_iam_member" "executor_managed_project_roles" {
  for_each = local.organization_scope_enabled ? toset([]) : toset(local.executor_project_roles)
  project  = local.effective_managed_project_id
  role     = each.value
  member   = "serviceAccount:${module.service_accounts.executor_service_account_email}"
}

# Organization scope roles for executor SA
resource "google_organization_iam_member" "executor_managed_organization_roles" {
  for_each = local.organization_scope_enabled ? toset(local.executor_organization_roles) : toset([])
  org_id   = var.organization_id
  role     = each.value
  member   = "serviceAccount:${module.service_accounts.executor_service_account_email}"
}


module "cloud_run" {
  source                                  = "./modules/cloud_run"
  service_name                            = var.cloud_run_service_name
  region                                  = var.region
  enable_vpc_sc                           = var.enable_vpc_sc
  executor_service_account_email          = module.service_accounts.executor_service_account_email
  image                                   = var.cloud_run_image
  tool_project_id                         = var.tool_project_id
  dataset_id                              = var.dataset_id
  effective_managed_project_id            = local.effective_managed_project_id
  organization_id                         = var.organization_id
  workspace_customer_id                   = var.workspace_customer_id
  scheduler_invoker_service_account_email = module.service_accounts.scheduler_invoker_service_account_email
  gas_invoker_service_account_email       = module.service_accounts.gas_invoker_service_account_email

  depends_on = [
    google_project_service.services,
    google_bigquery_dataset_iam_member.executor_bigquery_data_editor,
    google_project_iam_member.executor_bigquery_job_user,

    google_project_iam_member.executor_managed_project_roles,
    google_organization_iam_member.executor_managed_organization_roles,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "scheduler_run_invoker" {
  project  = var.tool_project_id
  location = var.region
  name     = module.cloud_run.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${module.service_accounts.scheduler_invoker_service_account_email}"
}

module "scheduler" {
  source                                  = "./modules/scheduler"
  tool_project_id                         = var.tool_project_id
  region                                  = var.region
  cloud_run_uri                           = module.cloud_run.uri
  scheduler_invoker_service_account_email = module.service_accounts.scheduler_invoker_service_account_email
  resource_collection_schedule            = var.resource_collection_schedule
  group_collection_schedule               = var.group_collection_schedule
  iam_policy_collection_schedule          = var.iam_policy_collection_schedule
  reconciliation_schedule                 = var.reconciliation_schedule
  revoke_expired_permissions_schedule     = var.revoke_expired_permissions_schedule
  iam_bindings_history_update_schedule    = var.iam_bindings_history_update_schedule
  scheduler_time_zone                     = var.scheduler_time_zone
  depends_on = [
    google_project_service.services,
    google_cloud_run_v2_service_iam_member.scheduler_run_invoker,
  ]
}

# --- VPC Service Controls (Optional) ---
resource "google_access_context_manager_service_perimeter" "tool_perimeter" {
  count  = var.enable_vpc_sc ? 1 : 0
  parent = var.access_policy_name
  name   = "${var.access_policy_name}/servicePerimeters/iam_access_manager_perimeter"
  title  = "iam-access-manager-perimeter"

  status {
    restricted_services = [
      "run.googleapis.com",
      "bigquery.googleapis.com",
      "secretmanager.googleapis.com",
      "cloudresourcemanager.googleapis.com",
      "cloudasset.googleapis.com",
      "cloudidentity.googleapis.com",
    "aiplatform.googleapis.com",
      "iamcredentials.googleapis.com",
      "artifactregistry.googleapis.com"
    ]
    resources = ["projects/${data.google_project.tool_project.number}"]
  }
}

module "monitoring" {
  source                         = "./modules/monitoring"
  tool_project_id                = var.tool_project_id
  alert_notification_email       = var.alert_notification_email
  alert_notification_webhook_url = var.alert_notification_webhook_url
  cloud_run_service_name         = module.cloud_run.name
}

resource "google_cloud_run_v2_service_iam_member" "gas_run_invoker" {
  project  = var.tool_project_id
  location = var.region
  name     = module.cloud_run.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${module.service_accounts.gas_invoker_service_account_email}"
}
