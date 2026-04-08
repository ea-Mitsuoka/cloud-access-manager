#!/usr/bin/env bash
set -euo pipefail

# 引数が渡されても無視する（後方互換性のため）
while [[ "$#" -gt 0 ]]; do
    shift
done

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="$ROOT_DIR/saas.env"

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "❌ Error: $CONFIG_FILE not found. Please setup saas.env first." >&2
    exit 1
fi

source "$CONFIG_FILE"

JOB_NAME="iam-principal-collection-daily"

echo "🚀 Triggering Cloud Scheduler job: ${JOB_NAME} ..."
gcloud scheduler jobs run "${JOB_NAME}" \
    --project "${TOOL_PROJECT_ID}" \
    --location "${REGION}"

echo "✅ Job triggered successfully. It runs asynchronously in the background."
echo "   Check Cloud Run logs or 'iam_pipeline_job_reports' in BigQuery for the result."
