#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT_DIR/terraform"
VARS_FILE="$ROOT_DIR/environment.auto.tfvars"

echo "=== Initiating Safe Teardown ==="

cd "$TF_DIR"

echo
echo "[1/2] Removing protected resources (BigQuery) and APIs from Terraform state..."

# Stateから逃がすリソースのリスト
protected_resources=(
  'module.bigquery.google_bigquery_dataset.iam'
  'module.bigquery.google_bigquery_table.iam_access_change_log'
  'module.bigquery.google_bigquery_table.iam_access_requests'
  'module.bigquery.google_bigquery_table.iam_pipeline_job_reports'
  'module.bigquery.google_bigquery_table.iam_policy_bindings_raw_history'
  'module.bigquery.google_bigquery_table.iam_policy_permissions'
  'module.bigquery.google_bigquery_table.iam_reconciliation_issues'
  'google_project_service.services["aiplatform.googleapis.com"]'
  'google_project_service.services["artifactregistry.googleapis.com"]'
  'google_project_service.services["bigquery.googleapis.com"]'
  'google_project_service.services["cloudasset.googleapis.com"]'
  'google_project_service.services["cloudbuild.googleapis.com"]'
  'google_project_service.services["cloudidentity.googleapis.com"]'
  'google_project_service.services["cloudresourcemanager.googleapis.com"]'
  'google_project_service.services["cloudscheduler.googleapis.com"]'
  'google_project_service.services["iam.googleapis.com"]'
  'google_project_service.services["iamcredentials.googleapis.com"]'
  'google_project_service.services["run.googleapis.com"]'
  'google_project_service.services["secretmanager.googleapis.com"]'
)

for resource in "${protected_resources[@]}"; do
  # Stateに存在する場合のみ rm を実行 (エラー回避)
  if terraform state list | grep -F -q "$resource"; then
    echo "Removing from state: $resource"
    terraform state rm "$resource" >/dev/null 2>&1
  fi
done
echo "✅ Protected resources successfully removed from state."

echo
echo "[2/2] Destroying the remaining environment..."
# 削除保護されているリソースはStateに存在しないため、安全にCloud Run等が削除される
terraform destroy -auto-approve -var-file="$VARS_FILE"

echo
echo "=== Teardown Finished Successfully ==="
echo "💡 Note: BigQuery data and essential Google Cloud APIs were preserved."
