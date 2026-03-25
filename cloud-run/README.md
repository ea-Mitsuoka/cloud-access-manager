# Cloud Run Executor

This service executes approved IAM requests and logs every execution into BigQuery.

## Endpoints

- `GET /healthz`
- `POST /execute` with payload: `{ "request_id": "..." }`
- `POST /collect/resources` (collect Folder/Project inventory to BigQuery history)
- `POST /collect/groups` (collect Google Groups and memberships to BigQuery)

## Environment variables

- `BQ_PROJECT_ID` (required)
- `BQ_DATASET_ID` (required)
- `MGMT_TARGET_PROJECT_ID` (required in project-only mode)
- `MGMT_TARGET_ORGANIZATION_ID` (optional; if set, project ancestry is validated against this org)
- `WORKSPACE_CUSTOMER_ID` (optional, default: `my_customer`)
- `EXECUTOR_IDENTITY` (optional)
- `WEBHOOK_SHARED_SECRET` (loaded from Secret Manager in Terraform deployment)

## Deploy example

```bash
gcloud run deploy iam-access-executor \
  --source cloud-run \
  --region asia-northeast1 \
  --service-account iam-executor@YOUR_PROJECT.iam.gserviceaccount.com \
  --set-env-vars BQ_PROJECT_ID=YOUR_PROJECT,BQ_DATASET_ID=YOUR_DATASET \
  --allow-unauthenticated
```

Use network-level controls (IAP/VPC-SC or ingress restrictions) and Secret Manager-backed `WEBHOOK_SHARED_SECRET`.

## Resource inventory collection

Call `/collect/resources` with the webhook token header.

```bash
curl -X POST \"https://<service-url>/collect/resources\" \\
  -H \"Content-Type: application/json\" \\
  -H \"X-Webhook-Token: <token>\" \\
  -d '{}'
```

For scheduled runs, Terraform provisions Cloud Scheduler with OIDC to call this endpoint daily.
Permission errors are returned as `FAILED_PERMISSION` with actionable `hint`, and also recorded in BigQuery `pipeline_job_reports`.

## Google group collection

Call `/collect/groups` with the webhook token header.

```bash
curl -X POST \"https://<service-url>/collect/groups\" \\
  -H \"Content-Type: application/json\" \\
  -H \"X-Webhook-Token: <token>\" \\
  -d '{}'
```

Note:

- Group collection uses Cloud Identity API and requires Workspace-side read permissions in addition to GCP IAM.
- Permission errors are returned as `FAILED_PERMISSION` with actionable `hint`, and also recorded in BigQuery `pipeline_job_reports`.
