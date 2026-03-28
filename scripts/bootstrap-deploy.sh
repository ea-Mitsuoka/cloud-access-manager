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
    case "${ans,,}" in
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

  escaped_value=$(printf '%s\n' "$value" | sed 's/[&/\]/\\&/g')

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
        echo "Terraform executor needs org-level roles to manage VPC-SC."
        current_user=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -n 1)
        read -r -p "Enter the principal (user or SA) for terraform apply [default: $current_user]: " tf_principal
        tf_principal="${tf_principal:-$current_user}"

        echo
        echo "The following roles will be granted at the organization level ($ORGANIZATION_ID) to '$tf_principal':"
        echo "  - Organization Admin (roles/resourcemanager.organizationAdmin)"
        echo "  - Access Context Manager Admin (roles/accesscontextmanager.policyAdmin)"
        echo
        if ask_yes_no "Proceed with granting these roles?" "n"; then
            gcloud organizations add-iam-policy-binding "$ORGANIZATION_ID" \
                --member="user:$tf_principal" \
                --role="roles/resourcemanager.organizationAdmin" \
                --condition=None >/dev/null
            gcloud organizations add-iam-policy-binding "$ORGANIZATION_ID" \
                --member="user:$tf_principal" \
                --role="roles/accesscontextmanager.policyAdmin" \
                --condition=None >/dev/null
            echo "Successfully granted organization-level roles."
        else
            echo "Skipped granting roles. Terraform apply may fail if the principal lacks permissions."
        fi
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
echo "[1/7] Syncing generated config files..."
bash "$ROOT_DIR/scripts/sync-config.sh" "$CONFIG_FILE"

echo
echo "[2/7] Bootstrapping tfstate bucket..."
bash "$ROOT_DIR/scripts/bootstrap-tfstate.sh" "$CONFIG_FILE"

echo
echo "[3/7] Terraform init..."
cd "$ROOT_DIR/terraform"
terraform init -backend-config="$ROOT_DIR/backend.hcl"

echo
echo "[4/7] Terraform plan..."
terraform plan -var-file="$ROOT_DIR/environment.auto.tfvars"

if [[ "$SKIP_APPLY" == "true" ]]; then
  echo
  echo "[5/7] Apply skipped by --skip-apply."
  exit 0
fi

echo
echo "[5/7] Terraform apply..."
if [[ "$AUTO_APPROVE" == "true" ]]; then
  terraform apply -auto-approve -var-file="$ROOT_DIR/environment.auto.tfvars"
else
  terraform apply -var-file="$ROOT_DIR/environment.auto.tfvars"
fi

echo
echo "[6/7] Applying BigQuery SQL definitions..."
require_cmd bq

sql_dir="$ROOT_DIR/build/sql"
if [[ ! -d "$sql_dir" ]] || [[ -z "$(find "$sql_dir" -name '*.sql')" ]]; then
  echo "Warning: No SQL files found in $sql_dir. Skipping BigQuery setup." >&2
  echo "Ensure you have run 'bash scripts/sync-config.sh' first." >&2
else
  # NOTE: The execution order is important.
  # Views depend on tables, so we can't just run them in alphabetical order.
  # This order is based on sql/README.md.
  sql_execution_order=(
    "001_tables.sql"
    "004_workbook_tables.sql"
    "002_views.sql"
    "005_workbook_views.sql"
    "007_seed_workbook_from_existing.sql"
    "003_reconciliation.sql"
    "006_matrix_pivot.sql"
    "008_update_bindings_history.sql"
  )

  for sql_filename in "${sql_execution_order[@]}"; do
    sql_file="$sql_dir/$sql_filename"
    if [[ -f "$sql_file" ]]; then
      echo "Executing: $sql_file"
      if ! bq query --project_id="$TOOL_PROJECT_ID" --use_legacy_sql=false < "$sql_file"; then
        echo "Error executing $sql_file. Please check BigQuery permissions and SQL syntax." >&2
        exit 1
      fi
    else
        echo "Warning: SQL file not found, skipping: $sql_file"
    fi
  done
  echo "All SQL files applied successfully."
fi

echo
echo "[7/7] Initial Data Collection"
if ask_yes_no "Run initial data collection jobs (resources and groups)? This may take a few minutes." y; then
  if terraform output cloud_run_url >/dev/null 2>&1; then
    cloud_run_url="$(terraform output -raw cloud_run_url)"
    echo "Collecting resource inventory..."
    bash "$ROOT_DIR/scripts/collect-resource-inventory.sh" --cloud-run-url "$cloud_run_url"
    echo "Collecting Google Groups..."
    bash "$ROOT_DIR/scripts/collect-google-groups.sh" --cloud-run-url "$cloud_run_url"
    echo "Initial data collection jobs triggered."
  else
    echo "Warning: Could not get Cloud Run URL from terraform output. Skipping data collection." >&2
  fi
else
  echo "Skipping initial data collection. You can run collection scripts manually later."
fi

echo
echo "=== Bootstrap & Deploy Complete ==="
if terraform output cloud_run_url >/dev/null 2>&1; then
  cloud_run_url="$(terraform output -raw cloud_run_url)"
  echo "Cloud Run URL: $cloud_run_url"
  echo "Please ensure this URL is set in your Google Apps Script properties (key: CLOUD_RUN_EXECUTE_URL)."
fi
