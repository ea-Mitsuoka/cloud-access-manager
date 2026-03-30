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
  GROUP_COLLECTION_SCHEDULE
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
        echo "⚠️ IMPORTANT: To apply VPC-SC, you MUST already have 'Organization Admin' and 'Access Context Manager Admin' roles."
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
bash "$ROOT_DIR/scripts/bootstrap-tfstate.sh" "$CONFIG_FILE"

echo
echo "[3/8] Preparing Docker Image (Artifact Registry)..."
echo "Ensuring required APIs are enabled..."
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com --project="$TOOL_PROJECT_ID"

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

echo "Building and pushing Docker image: $CLOUD_RUN_IMAGE"
docker build --platform linux/amd64 -t "$CLOUD_RUN_IMAGE" "$ROOT_DIR/cloud-run"
docker push "$CLOUD_RUN_IMAGE"

echo
echo "[4/8] Terraform init..."

cd "$ROOT_DIR/terraform"
terraform init -backend-config="$ROOT_DIR/backend.hcl"

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
      if ! bq query \
            --project_id="$TOOL_PROJECT_ID" \
            --use_legacy_sql=false \
            --display_report_line=true \
            "$(cat "$sql_file")"; then
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
echo "[8/8] Initial Data Collection & Seeding"
if ask_yes_no "Run initial data collection jobs and seed existing permissions? This may take a few minutes." y; then
  echo "Triggering data collection jobs via Cloud Scheduler (Async)..."
  bash "$ROOT_DIR/scripts/collect-resource-inventory.sh" || true
  bash "$ROOT_DIR/scripts/collect-google-groups.sh" || true
  bash "$ROOT_DIR/scripts/collect-iam-policies.sh" || true
  
  echo "Waiting for IAM policies to be collected into BigQuery before seeding..."
  echo "(This usually takes 1-3 minutes. Polling every 10 seconds...)"
  
  MAX_WAIT=300
  WAIT_INTERVAL=10
  elapsed=0
  seed_ready=false
  
  while [[ $elapsed -lt $MAX_WAIT ]]; do
    # 収集データが1件でも入ったか確認
    row_count=$(bq query --project_id="$TOOL_PROJECT_ID" --use_legacy_sql=false --format=csv "SELECT COUNT(1) FROM \`$TOOL_PROJECT_ID.$BQ_DATASET_ID.iam_policy_permissions\`" 2>/dev/null | tail -n 1 | tr -d '
')
    
    if [[ "$row_count" =~ ^[0-9]+$ ]] && [[ "$row_count" -gt 0 ]]; then
      echo "✅ Data collection detected ($row_count rows). Proceeding to seed..."
      seed_ready=true
      break
    fi
    
    echo "⏳ Waiting... (${elapsed}s / ${MAX_WAIT}s)"
    sleep $WAIT_INTERVAL
    elapsed=$((elapsed + WAIT_INTERVAL))
  done

  if [[ "$seed_ready" == "true" ]]; then
    # 冪等性（Idempotency）の担保: Historyテーブルが空の場合のみSeedを実行する
    seed_count=$(bq query --project_id="$TOOL_PROJECT_ID" --use_legacy_sql=false --format=csv "SELECT COUNT(1) FROM \`$TOOL_PROJECT_ID.$BQ_DATASET_ID.iam_permission_bindings_history\`" 2>/dev/null | tail -n 1 | tr -d '
')
    
    if [[ "$seed_count" =~ ^[0-9]+$ ]] && [[ "$seed_count" -eq 0 ]]; then
      echo "Executing: 007_seed_workbook_from_existing.sql"
      bq query --project_id="$TOOL_PROJECT_ID" --use_legacy_sql=false < "$ROOT_DIR/build/sql/007_seed_workbook_from_existing.sql"
      echo "✅ Initial data seeding finished."
    elif [[ "$seed_count" =~ ^[0-9]+$ ]]; then
      echo "✅ History table already contains data ($seed_count rows). Skipping seed to prevent duplication."
    else
      echo "⚠️ Could not verify table row count. Skipping seed to prevent potential duplication."
    fi
  else
    echo "⚠️ Warning: IAM policies collection did not finish within $MAX_WAIT seconds."
    echo "👉 Skipping automatic seed. Please run '007_seed_workbook_from_existing.sql' manually in BigQuery later."
  fi
else
  echo "Skipping initial data collection. You can run collection scripts manually later."
fi

echo
echo "=== Bootstrap & Deploy Complete ==="
cd "$ROOT_DIR/terraform"
if terraform output cloud_run_url >/dev/null 2>&1; then
  cloud_run_url="$(terraform output -raw cloud_run_url)"
  echo "Cloud Run URL: $cloud_run_url"
  echo "Please ensure this URL is set in your Google Apps Script properties (key: CLOUD_RUN_EXECUTE_URL)."
fi
cd "$ROOT_DIR"
