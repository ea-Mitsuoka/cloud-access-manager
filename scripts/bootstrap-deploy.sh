#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="$ROOT_DIR/saas.env"
AUTO_APPROVE="false"
SKIP_APPLY="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIG_FILE="$2"
      shift 2
      ;;
    --auto-approve)
      AUTO_APPROVE="true"
      shift
      ;;
    --skip-apply)
      SKIP_APPLY="true"
      shift
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: bash scripts/bootstrap-deploy.sh [options]

Options:
  --config <path>   Use custom env file (default: ./saas.env)
  --auto-approve    Apply terraform with -auto-approve
  --skip-apply      Run through plan only (no apply)
  -h, --help        Show this help
USAGE
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

ask_yes_no() {
  local prompt="$1"
  local default="${2:-y}"
  local ans
  while true; do
    if [[ "$default" == "y" ]]; then
      read -r -p "$prompt [Y/n]: " ans
      ans="${ans:-Y}"
    else
      read -r -p "$prompt [y/N]: " ans
      ans="${ans:-N}"
    fi
    ans_lower=$(echo "$ans" | tr "[:upper:]" "[:lower:]")
    case "$ans_lower" in
      y|yes) return 0 ;;
      n|no) return 1 ;;
      *) echo "Please answer y or n." ;;
    esac
  done
}

update_config() {
  local key="$1"
  local value="$2"
  local file="$3"

  escaped_value=$(printf '%s
' "$value" | sed 's/[&/\]/\&/g')

  if grep -q -E "^${key}=" "$file"; then
    tmp_file=$(mktemp)
    sed "s~^${key}=.*~${key}=${escaped_value}~" "$file" > "$tmp_file"
    mv "$tmp_file" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

cron_to_daily_minutes() {
  local expr="$1"
  local minute hour
  if [[ "$expr" =~ ^([0-9]{1,2})[[:space:]]+([0-9]{1,2})[[:space:]]+\*[[:space:]]+\*[[:space:]]+\*$ ]]; then
    minute="${BASH_REMATCH[1]}"
    hour="${BASH_REMATCH[2]}"
    if ((minute >= 0 && minute <= 59 && hour >= 0 && hour <= 23)); then
      echo $((hour * 60 + minute))
      return 0
    fi
  fi
  return 1
}

assert_schedule_before() {
  local left_name="$1"
  local left_expr="$2"
  local right_name="$3"
  local right_expr="$4"
  local left_min right_min

  if ! left_min="$(cron_to_daily_minutes "$left_expr")"; then
    echo "WARN: Skip strict order check for $left_name. Unsupported cron format: $left_expr"
    return 0
  fi
  if ! right_min="$(cron_to_daily_minutes "$right_expr")"; then
    echo "WARN: Skip strict order check for $right_name. Unsupported cron format: $right_expr"
    return 0
  fi

  if ((left_min >= right_min)); then
    echo "Invalid scheduler order: $left_name ($left_expr) must be earlier than $right_name ($right_expr)." >&2
    exit 1
  fi
}

validate_scheduler_order() {
  assert_schedule_before "REVOKE_EXPIRED_PERMISSIONS_SCHEDULE" "$REVOKE_EXPIRED_PERMISSIONS_SCHEDULE" "RESOURCE_COLLECTION_SCHEDULE" "$RESOURCE_COLLECTION_SCHEDULE"
  assert_schedule_before "REVOKE_EXPIRED_PERMISSIONS_SCHEDULE" "$REVOKE_EXPIRED_PERMISSIONS_SCHEDULE" "PRINCIPAL_COLLECTION_SCHEDULE" "$PRINCIPAL_COLLECTION_SCHEDULE"
  assert_schedule_before "REVOKE_EXPIRED_PERMISSIONS_SCHEDULE" "$REVOKE_EXPIRED_PERMISSIONS_SCHEDULE" "IAM_POLICY_COLLECTION_SCHEDULE" "$IAM_POLICY_COLLECTION_SCHEDULE"
  assert_schedule_before "RESOURCE_COLLECTION_SCHEDULE" "$RESOURCE_COLLECTION_SCHEDULE" "RECONCILIATION_SCHEDULE" "$RECONCILIATION_SCHEDULE"
  assert_schedule_before "PRINCIPAL_COLLECTION_SCHEDULE" "$PRINCIPAL_COLLECTION_SCHEDULE" "RECONCILIATION_SCHEDULE" "$RECONCILIATION_SCHEDULE"
  assert_schedule_before "IAM_POLICY_COLLECTION_SCHEDULE" "$IAM_POLICY_COLLECTION_SCHEDULE" "RECONCILIATION_SCHEDULE" "$RECONCILIATION_SCHEDULE"
  assert_schedule_before "RECONCILIATION_SCHEDULE" "$RECONCILIATION_SCHEDULE" "IAM_BINDINGS_HISTORY_UPDATE_SCHEDULE" "$IAM_BINDINGS_HISTORY_UPDATE_SCHEDULE"
  assert_schedule_before "IAM_BINDINGS_HISTORY_UPDATE_SCHEDULE" "$IAM_BINDINGS_HISTORY_UPDATE_SCHEDULE" "IAM_ROLE_DISCOVERY_SCHEDULE" "$IAM_ROLE_DISCOVERY_SCHEDULE"
}

if [[ ! -f "$CONFIG_FILE" ]]; then
  if [[ -f "$ROOT_DIR/saas.env.example" ]] && ask_yes_no "Config not found. Create from saas.env.example?" y; then
    cp "$ROOT_DIR/saas.env.example" "$CONFIG_FILE"
    echo "Created: $CONFIG_FILE"
    echo "Please edit values first, then rerun this script."
    exit 0
  fi
  echo "Config file not found: $CONFIG_FILE" >&2
  exit 1
fi

require_cmd gcloud
require_cmd terraform
require_cmd bash
require_cmd docker

ensure_docker_running() {
  if docker system info >/dev/null 2>&1; then
    return 0
  fi
  echo
  echo "⚠️  Docker daemon is not running."
  if [[ "$(uname -s)" == "Darwin" ]]; then
    if ask_yes_no "Would you like me to try starting Docker for you?" "y"; then
      if command -v orb >/dev/null 2>&1; then
        echo "🚀 Starting OrbStack..."
        orb start
      elif command -v colima >/dev/null 2>&1; then
        echo "🚀 Starting Colima..."
        colima start
      elif command -v rdctl >/dev/null 2>&1; then
        echo "🚀 Starting Rancher Desktop..."
        rdctl start
      elif [[ -d "/Applications/Docker.app" ]]; then
        echo "🚀 Starting Docker Desktop..."
        open --background -a Docker
      else
        echo "❌ Could not detect a known Docker manager. Please start Docker manually."
        exit 1
      fi

      echo -n "⏳ Waiting for Docker daemon to be ready..."
      local max_wait=60
      local elapsed=0
      while ! docker system info >/dev/null 2>&1; do
        sleep 2
        elapsed=$((elapsed + 2))
        echo -n "."
        if [[ $elapsed -ge $max_wait ]]; then
          echo " Timeout! Please check your Docker app and start it manually."
          exit 1
        fi
      done
      echo " ✅ Docker is up!"
      echo
    else
      echo "Please start Docker manually and rerun the script."
      exit 1
    fi
  else
    echo "Please start the Docker daemon (e.g., 'sudo systemctl start docker') and rerun the script."
    exit 1
  fi
}

ensure_docker_running

# shellcheck disable=SC1090
set -a
source "$CONFIG_FILE"
set +a

required=(
  TOOL_PROJECT_ID
  REGION
  BQ_DATASET_ID
  CLOUD_RUN_SERVICE_NAME
  CLOUD_RUN_IMAGE
  WORKSPACE_CUSTOMER_ID
  RESOURCE_COLLECTION_SCHEDULE
  PRINCIPAL_COLLECTION_SCHEDULE
  IAM_POLICY_COLLECTION_SCHEDULE
  IAM_ROLE_DISCOVERY_SCHEDULE
  RECONCILIATION_SCHEDULE
  REVOKE_EXPIRED_PERMISSIONS_SCHEDULE
  IAM_BINDINGS_HISTORY_UPDATE_SCHEDULE
  SCHEDULER_TIME_ZONE
  BQ_LOCATION
  TFSTATE_BUCKET
  TFSTATE_PREFIX
  TFSTATE_LOCATION
)

for key in "${required[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    echo "Missing required key in $CONFIG_FILE: $key" >&2
    exit 1
  fi
done

validate_scheduler_order

MANAGED_EFFECTIVE="${MANAGED_PROJECT_ID:-$TOOL_PROJECT_ID}"
ORG_EFFECTIVE="${ORGANIZATION_ID:-}"

echo
echo "=== Configuration Summary ==="
echo "Config file            : $CONFIG_FILE"
echo "Tool project           : $TOOL_PROJECT_ID"
echo "Managed project        : $MANAGED_EFFECTIVE"
echo "Organization scope     : ${ORG_EFFECTIVE:-<project-only>}"
echo "Region                 : $REGION"
echo "Dataset                : $BQ_DATASET_ID"
echo "Cloud Run service      : $CLOUD_RUN_SERVICE_NAME"
echo "Cloud Run image        : $CLOUD_RUN_IMAGE"
echo "Workspace customer ID  : $WORKSPACE_CUSTOMER_ID"
echo "Resource schedule      : $RESOURCE_COLLECTION_SCHEDULE"
echo "Role discovery schedule: $IAM_ROLE_DISCOVERY_SCHEDULE"
echo "Scheduler time zone    : $SCHEDULER_TIME_ZONE"
echo "TF state bucket        : $TFSTATE_BUCKET"
echo "TF state prefix        : $TFSTATE_PREFIX"
echo

# VPC-SC setting interactive
echo "--- VPC Service Controls Setup (Optional) ---"
if [[ -z "${ORGANIZATION_ID:-}" ]]; then
    echo "VPC-SC requires Organization Scope. Skipping."
    update_config "enable_vpc_sc" "false" "$CONFIG_FILE"
else
    current_vpc_sc_enabled=$(grep -E '^enable_vpc_sc=' "$CONFIG_FILE" | cut -d= -f2)
    default_answer="n"
    if [[ "$current_vpc_sc_enabled" == "true" ]]; then
        default_answer="y"
    fi

    if ask_yes_no "Enable VPC Service Controls for enhanced security? (Requires Organization Admin roles)" "$default_answer"; then
        update_config "enable_vpc_sc" "true" "$CONFIG_FILE"
        current_access_policy_name=$(grep -E '^access_policy_name=' "$CONFIG_FILE" | cut -d= -f2)

        while true; do
            read -r -p "Enter Access Policy name (e.g. accessPolicies/123456789): " access_policy_name
            access_policy_name="${access_policy_name:-$current_access_policy_name}"
            if [[ -n "$access_policy_name" ]]; then
                update_config "access_policy_name" "$access_policy_name" "$CONFIG_FILE"
                echo "VPC-SC enabled. Access Policy: $access_policy_name"
                break
            else
                echo "Access Policy name cannot be empty."
            fi
        done

        echo
        echo "⚠️ IMPORTANT: To apply VPC-SC, you MUST already have 'Organization Viewer' and 'Access Context Manager Admin' roles."
        echo "This script will NOT automatically grant these highly privileged roles."
    else
        update_config "enable_vpc_sc" "false" "$CONFIG_FILE"
        echo "VPC-SC disabled."
    fi
fi
echo

if ! ask_yes_no "Proceed with bootstrap + deploy workflow?" y; then
  echo "Cancelled."
  exit 0
fi

echo
echo "[1/8] Syncing generated config files..."
bash "$ROOT_DIR/scripts/sync-config.sh" "$CONFIG_FILE"

echo
echo "[2/8] Bootstrapping tfstate bucket..."
if ! bash "$ROOT_DIR/scripts/bootstrap-tfstate.sh" "$CONFIG_FILE"; then
  echo "❌ Error: tfstate bucketのセットアップに失敗しました。詳細なエラーを確認してください。" >&2
  exit 1
fi

echo
echo "[3/8] Preparing Docker Image (Artifact Registry)..."
echo "Ensuring required APIs are enabled..."
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com --project="$TOOL_PROJECT_ID" --quiet

# イメージURLからリポジトリ名（iam-access-repo）を自動抽出
AR_REPO_NAME=$(echo "$CLOUD_RUN_IMAGE" | cut -d/ -f3)

if ! gcloud artifacts repositories describe "$AR_REPO_NAME" --project="$TOOL_PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
  echo "Creating Artifact Registry repository: $AR_REPO_NAME"
  gcloud artifacts repositories create "$AR_REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$TOOL_PROJECT_ID" \
    --description="Created by bootstrap script"
fi

echo "Configuring Docker auth..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# cloud-runディレクトリのコンテンツからハッシュを計算してタグを生成
if command -v shasum >/dev/null 2>&1; then
  HASH_CMD="shasum -a 256"
else
  HASH_CMD="sha256sum"
fi
# 隠しファイルやpycacheを除外してハッシュを計算
CONTENT_HASH=$(find "$ROOT_DIR/cloud-run" -type f -not -path "*/\.*" -not -path "*/__pycache__/*" | sort | xargs $HASH_CMD | $HASH_CMD | cut -d' ' -f1 | cut -c1-8)
IMAGE_TAG="hash-${CONTENT_HASH}"

BASE_IMAGE_URL="${CLOUD_RUN_IMAGE%%:*}"
DEPLOY_IMAGE_URL="${BASE_IMAGE_URL}:${IMAGE_TAG}"

echo "Building and pushing Docker image: $DEPLOY_IMAGE_URL"
docker build --platform linux/amd64 -t "$DEPLOY_IMAGE_URL" -t "$BASE_IMAGE_URL:latest" "$ROOT_DIR/cloud-run"
docker push "$DEPLOY_IMAGE_URL"
docker push "$BASE_IMAGE_URL:latest"

# Terraform用の変数ファイルを新しいイメージURLで上書き
TFVARS_FILE="$ROOT_DIR/environment.auto.tfvars"
if grep -q "^cloud_run_image" "$TFVARS_FILE"; then
  tmp_file=$(mktemp)
  sed "s~^cloud_run_image.*~cloud_run_image = \"${DEPLOY_IMAGE_URL}\"~" "$TFVARS_FILE" > "$tmp_file"
  mv "$tmp_file" "$TFVARS_FILE"
else
  echo "cloud_run_image = \"${DEPLOY_IMAGE_URL}\"" >> "$TFVARS_FILE"
fi

echo
echo "[4/8] Terraform init..."

cd "$ROOT_DIR/terraform"
terraform init -backend-config="$ROOT_DIR/backend.hcl"

echo
echo "[4.5/8] Importing existing BigQuery & API resources into Terraform state..."
cd "$ROOT_DIR/terraform"

import_resource() {
  local tf_resource="$1"
  local gcp_id="$2"
  if ! terraform state list | grep -F -q "$tf_resource"; then
    echo "Attempting to import $tf_resource..."
    terraform import -var-file="$ROOT_DIR/environment.auto.tfvars" "$tf_resource" "$gcp_id" >/dev/null 2>&1 || echo " 👉 Not found in GCP. Will be created."
  fi
}

# 1. BigQueryのImport
BQ_DATASET_GCP_ID="projects/$TOOL_PROJECT_ID/datasets/$BQ_DATASET_ID"
import_resource "module.bigquery.google_bigquery_dataset.iam" "$BQ_DATASET_GCP_ID"

bq_tables=(
  "iam_access_change_log"
  "iam_access_requests"
  "iam_pipeline_job_reports"
  "iam_policy_bindings_raw_history"
  "iam_policy_permissions"
  "iam_reconciliation_issues"
)
for table in "${bq_tables[@]}"; do
  import_resource "module.bigquery.google_bigquery_table.$table" "$BQ_DATASET_GCP_ID/tables/$table"
done

# 2. APIリソースのImport
apis=(
  "aiplatform.googleapis.com"
  "artifactregistry.googleapis.com"
  "bigquery.googleapis.com"
  "cloudasset.googleapis.com"
  "cloudbuild.googleapis.com"
  "cloudidentity.googleapis.com"
  "cloudresourcemanager.googleapis.com"
  "cloudscheduler.googleapis.com"
  "iam.googleapis.com"
  "iamcredentials.googleapis.com"
  "iap.googleapis.com"
  "run.googleapis.com"
  "secretmanager.googleapis.com"
)
for api in "${apis[@]}"; do
  import_resource "google_project_service.services["$api"]" "$TOOL_PROJECT_ID/$api"
done

# 3. 旧設計（顧客側IAMをTerraformで管理）からの移行:
#    stateに残っている対象IAMリソースを退避し、意図しないdestroyを防止する。
echo "Checking legacy tenant IAM resources in Terraform state..."
legacy_state_resources=$(
  terraform state list 2>/dev/null | \
    grep -E '^(google_project_iam_member\.executor_managed_project_roles|google_organization_iam_member\.executor_managed_organization_roles)' || true
)
if [[ -n "$legacy_state_resources" ]]; then
  echo "Found legacy tenant IAM resources in state. Detaching from state to prevent accidental revocation..."
  while IFS= read -r addr; do
    [[ -z "$addr" ]] && continue
    terraform state rm "$addr" >/dev/null
    echo "  - detached: $addr"
  done <<< "$legacy_state_resources"
  echo "✅ Legacy tenant IAM resources were detached from state."
fi

echo
echo "[5/8] Terraform plan..."
terraform plan -var-file="$ROOT_DIR/environment.auto.tfvars"

if [[ "$SKIP_APPLY" == "true" ]]; then
  echo
  echo "[6/8] Apply skipped by --skip-apply."
  exit 0
fi

echo
echo "[6/8] Terraform apply..."
if [[ "$AUTO_APPROVE" == "true" ]]; then
  terraform apply -auto-approve -var-file="$ROOT_DIR/environment.auto.tfvars"
else
  terraform apply -var-file="$ROOT_DIR/environment.auto.tfvars"
fi

cd "$ROOT_DIR"

echo
echo "[7/8] Applying BigQuery SQL definitions..."
require_cmd bq

sql_dir="$ROOT_DIR/build/sql"
if [[ ! -d "$sql_dir" ]] || [[ -z "$(find "$sql_dir" -name '*.sql')" ]]; then
  echo "Warning: No SQL files found in $sql_dir. Skipping BigQuery setup." >&2
  echo "Ensure you have run 'bash scripts/sync-config.sh' first." >&2
else
  # 削除済みのSQLファイルをリストからパージし、正しい依存順序で実行
  sql_execution_order=(
    "001_tables.sql"
    "004_workbook_tables.sql"
    "002_views.sql"
    "005_workbook_views.sql"
  )

  for sql_filename in "${sql_execution_order[@]}"; do
    sql_file="$sql_dir/$sql_filename"
    if [[ -f "$sql_file" ]]; then
      echo "--------------------------------------------------------"
      echo "📄 Executing SQL: $sql_filename"

      # 複雑なView定義で固まらないよう、一時ファイル経由でクエリを実行
      # また、実行状況がわかるように stdout を逐次表示する
      # 標準入力から流し込む形式に戻しつつ、余計なフラグを削除して安定性を優先
      if ! bq query --project_id="$TOOL_PROJECT_ID" --use_legacy_sql=false < "$sql_file"; then
        echo "❌ Error executing $sql_filename. Please check BigQuery console for details." >&2
        exit 1
      fi
      echo "✅ Successfully applied: $sql_filename"
    else
      echo "⚠️ Warning: SQL file not found, skipping: $sql_file"
    fi
  done
  echo "All SQL files applied successfully."
fi

echo

echo "=== Bootstrap & Deploy Complete ==="
cd "$ROOT_DIR/terraform"
if terraform output cloud_run_url >/dev/null 2>&1; then
  cloud_run_url="$(terraform output -raw cloud_run_url)"
  echo "Cloud Run URL: $cloud_run_url"

  # apps-script/script-properties.json の CLOUD_RUN_EXECUTE_URL を自動上書き
  json_file="$ROOT_DIR/apps-script/script-properties.json"
  if [[ -f "$json_file" ]]; then
    execute_url="${cloud_run_url}/execute"
    tmp_json=$(mktemp)
    # URL内のスラッシュと衝突しないようセパレータに「~」を使用
    sed "s~\"CLOUD_RUN_EXECUTE_URL\"[[:space:]]*:[[:space:]]*\".*\"~\"CLOUD_RUN_EXECUTE_URL\": \"${execute_url}\"~" "$json_file" > "$tmp_json"
    mv "$tmp_json" "$json_file"
    echo "✅ Automatically updated CLOUD_RUN_EXECUTE_URL in apps-script/script-properties.json"
    echo "👉 You can now safely copy properties from: cat apps-script/script-properties.json"
  else
    echo "⚠️ apps-script/script-properties.json not found."
    echo "Please ensure this URL is set in your Google Apps Script properties (key: CLOUD_RUN_EXECUTE_URL)."
  fi
fi
cd "$ROOT_DIR"

echo "========================================================"
echo "✅ SaaSインフラの構築（コントロールプレーン）が完了しました！"
echo "========================================================"
echo "ℹ️ テナントのオンボーディング（権限付与と初期データ収集）は、"
echo "デプロイ完了後に docs/operation/operations-runbook.md の"
echo "「3. テナント・オンボーディングと初期データ収集」に従って実施してください。"
