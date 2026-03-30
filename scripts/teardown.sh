#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="$ROOT_DIR/terraform"
VARS_FILE="$ROOT_DIR/environment.auto.tfvars"

echo "=== Initiating Safe Teardown ==="

cd "$TF_DIR"

echo
echo "[1/2] Dynamically removing protected resources (BigQuery) and APIs from Terraform state..."

# 現在のStateリストを取得
state_list=$(terraform state list)

# 1. BigQuery関連の全リソース（データセットとテーブル）を抽出してrm
echo ">> Protecting BigQuery resources..."
for resource in $(echo "$state_list" | grep -E "^module\.bigquery\." || true); do
  echo "Removing from state: $resource"
  terraform state rm "$resource" >/dev/null 2>&1
done

# 2. Google Cloud API の有効化設定を抽出してrm
echo ">> Protecting Google Cloud API settings..."
for resource in $(echo "$state_list" | grep -E "^google_project_service\.services" || true); do
  echo "Removing from state: $resource"
  terraform state rm "$resource" >/dev/null 2>&1
done

echo "✅ Protected resources successfully removed from state."

echo
echo "[2/2] Destroying the remaining environment..."
# 保護対象はStateから消えているため、Cloud Run等のみが安全に破壊される
terraform destroy -auto-approve -var-file="$VARS_FILE"

echo
echo "=== Teardown Finished Successfully ==="
echo "💡 Note: BigQuery data and essential Google Cloud APIs were preserved."
