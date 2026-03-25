# Cloud Run Executor

This service executes approved IAM requests and logs every execution into BigQuery.

## Endpoints

- `GET /healthz`
- `POST /execute` with payload: `{ "request_id": "..." }`

## Environment variables

- `BQ_PROJECT_ID` (required)
- `BQ_DATASET_ID` (required)
- `MGMT_TARGET_PROJECT_ID` (required in project-only mode)
- `MGMT_TARGET_ORGANIZATION_ID` (optional; if set, project ancestry is validated against this org)
- `EXECUTOR_IDENTITY` (optional)
- `WEBHOOK_SHARED_SECRET` (optional)

## Deploy example

```bash
gcloud run deploy iam-access-executor \
  --source cloud-run \
  --region asia-northeast1 \
  --service-account iam-executor@YOUR_PROJECT.iam.gserviceaccount.com \
  --set-env-vars BQ_PROJECT_ID=YOUR_PROJECT,BQ_DATASET_ID=YOUR_DATASET,WEBHOOK_SHARED_SECRET=YOUR_SECRET \
  --allow-unauthenticated
```

Use network-level controls (IAP/VPC-SC or ingress restrictions) and `WEBHOOK_SHARED_SECRET` at minimum.
