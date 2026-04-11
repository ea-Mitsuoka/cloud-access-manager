#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="$ROOT_DIR/saas.env"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "❌ Error: $CONFIG_FILE not found. Please setup saas.env first." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$CONFIG_FILE"
set +a

required=(
  TOOL_PROJECT_ID
  REGION
  BQ_DATASET_ID
)
for key in "${required[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    echo "❌ Error: Missing required key in $CONFIG_FILE: $key" >&2
    exit 1
  fi
done

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "❌ Error: Required command not found: $1" >&2
    exit 1
  fi
}

require_cmd gcloud
require_cmd bq

echo "テナントの初期データ収集（オンボーディング）を開始します..."
echo "Project: $TOOL_PROJECT_ID, Region: $REGION, Dataset: $BQ_DATASET_ID"

# 1. 収集ジョブの実行（非同期）
gcloud scheduler jobs run iam-resource-inventory-daily --project="$TOOL_PROJECT_ID" --location="$REGION"
gcloud scheduler jobs run iam-principal-collection-daily --project="$TOOL_PROJECT_ID" --location="$REGION"
gcloud scheduler jobs run iam-policy-collection-daily --project="$TOOL_PROJECT_ID" --location="$REGION"

echo "データ収集の完了待機（約90秒）..."
sleep 90

echo "最新ジョブレポートを確認します..."
bq query --project_id="$TOOL_PROJECT_ID" --use_legacy_sql=false <<SQL
SELECT
  job_type,
  result,
  error_code,
  error_message,
  occurred_at
FROM \`${TOOL_PROJECT_ID}.${BQ_DATASET_ID}.iam_pipeline_job_reports\`
WHERE job_type IN ('RESOURCE_COLLECTION', 'PRINCIPAL_COLLECTION', 'IAM_POLICY_COLLECTION')
ORDER BY occurred_at DESC
LIMIT 20
SQL

# 2. 初期シードデータの生成（007_seed...）
echo "初期シードSQLを実行します..."
bq query --project_id="$TOOL_PROJECT_ID" --use_legacy_sql=false < "$ROOT_DIR/build/sql/007_seed_workbook_from_existing.sql"

echo "✅ オンボーディング処理が完了しました。"
