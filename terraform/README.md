# Terraform

## Prerequisites

- Terraform 1.6+
- gcloud auth configured for target project

## Usage

```bash
bash ../scripts/sync-config.sh
bash ../scripts/bootstrap-tfstate.sh
cd terraform
terraform init -backend-config=../backend.hcl
terraform plan -var-file=../environment.auto.tfvars
terraform apply -var-file=../environment.auto.tfvars
```

## Notes

- `tool_project_id` is the deployment project for this tool stack.
- `managed_project_id` is the managed target project. If empty (`""`), `tool_project_id` is used.
- `organization_id` is optional. If empty (`""`), this stack is treated as project-only management scope.
- `workspace_customer_id` controls Cloud Identity group search target (default: `my_customer`).
- `resource_collection_schedule` controls the daily Cloud Scheduler run for `/collect/resources`.
- `group_collection_schedule` controls the daily Cloud Scheduler run for `/collect/groups`.
- `scheduler_time_zone` controls Cloud Scheduler time zone for both jobs.
- You can confirm selected scope with `terraform output management_scope`.
- You can confirm current target with `terraform output effective_managed_project_id`.
- You can confirm scheduler job with `terraform output resource_inventory_scheduler_job`.
- You can confirm groups scheduler job with `terraform output group_collection_scheduler_job`.
- Enabled APIs are protected with `lifecycle.prevent_destroy = true` and `disable_on_destroy = false`, so `destroy` will not disable them.
- This MVP creates dataset, required BQ tables, executor service account, and Cloud Run service.
- Executor SA IAM is scoped for least privilege: dataset-level BigQuery editor plus managed target scope (`managed_project_id` or `organization_id`).
- Container image must be built/pushed separately and passed via `cloud_run_image`.
- Detailed role matrix and operational commands: `docs/operations-runbook.md`.
