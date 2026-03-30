#!/usr/bin/env bash
set -euo pipefail

# === 原因分析用：デバッグモードを有効化 ===
set -x

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT_DIR/terraform"
VARS_FILE="$ROOT_DIR/environment.auto.tfvars"

echo "=== Initiating Safe Teardown ==="

cd "$TF_DIR"

echo "[1/2] Dynamically removing protected resources (BigQuery) and APIs from Terraform state..."

# Stateリストの取得
state_list=$(terraform state list)

echo ">> Protecting BigQuery resources..."
bq_resources=$(echo "$state_list" | grep -E "^module\.bigquery\." | grep -v "iam_policy_permissions" || true)
if [[ -n "$bq_resources" ]]; then
  while IFS= read -r resource; do
    echo "Removing from state: $resource"
    # エラー出力を隠さず、そのまま実行させる
    terraform state rm "$resource"
  done <<< "$bq_resources"
fi

echo ">> Protecting Google Cloud API settings..."
api_resources=$(echo "$state_list" | grep -E "^google_project_service\.services" || true)
if [[ -n "$api_resources" ]]; then
  while IFS= read -r resource; do
    echo "Removing from state: $resource"
    # エラー出力を隠さず、そのまま実行させる
    terraform state rm "$resource"
  done <<< "$api_resources"
fi

echo "✅ Protected resources successfully removed from state."

# デバッグモードを解除（destroyのログが長くなりすぎるのを防ぐため）
set +x

echo
echo "[2/2] Destroying the remaining environment..."
terraform destroy -auto-approve -var-file="$VARS_FILE"

echo
echo "=== Teardown Finished Successfully ==="
