# Terraform

## Prerequisites

- Terraform 1.6+
- gcloud auth configured for target project

## Usage

```bash
cd terraform
terraform init
terraform plan -var-file=../environment.auto.tfvars
terraform apply -var-file=../environment.auto.tfvars
```

## Notes

- `tool_project_id` is the deployment project for this tool stack.
- `managed_project_id` is the managed target project. If empty (`""`), `tool_project_id` is used.
- `organization_id` is optional. If empty (`""`), this stack is treated as project-only management scope.
- You can confirm selected scope with `terraform output management_scope`.
- You can confirm current target with `terraform output effective_managed_project_id`.
- Enabled APIs are protected with `lifecycle.prevent_destroy = true` and `disable_on_destroy = false`, so `destroy` will not disable them.
- This MVP creates dataset, required BQ tables, executor service account, and Cloud Run service.
- Container image must be built/pushed separately and passed via `cloud_run_image`.
