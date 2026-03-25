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
  WEBHOOK_SECRET_NAME
  WORKSPACE_CUSTOMER_ID
  RESOURCE_COLLECTION_SCHEDULE
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
echo "Webhook secret name    : $WEBHOOK_SECRET_NAME"
echo "Workspace customer ID  : $WORKSPACE_CUSTOMER_ID"
echo "Resource schedule      : $RESOURCE_COLLECTION_SCHEDULE"
echo "Scheduler time zone    : $SCHEDULER_TIME_ZONE"
echo "TF state bucket        : $TFSTATE_BUCKET"
echo "TF state prefix        : $TFSTATE_PREFIX"
echo

if ! ask_yes_no "Proceed with bootstrap + deploy workflow?" y; then
  echo "Cancelled."
  exit 0
fi

echo
echo "[1/6] Syncing generated config files..."
bash "$ROOT_DIR/scripts/sync-config.sh" "$CONFIG_FILE"

echo
echo "[2/6] Bootstrapping tfstate bucket..."
bash "$ROOT_DIR/scripts/bootstrap-tfstate.sh" "$CONFIG_FILE"

echo
echo "[3/6] Preparing webhook secret in Secret Manager..."
if gcloud secrets describe "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID" >/dev/null 2>&1; then
  echo "Secret exists: $WEBHOOK_SECRET_NAME"
else
  echo "Creating secret: $WEBHOOK_SECRET_NAME"
  gcloud secrets create "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID" --replication-policy=automatic
fi

if ask_yes_no "Add a new secret version now?" n; then
  read -r -s -p "Enter webhook secret value: " secret_value
  echo
  if [[ -z "$secret_value" ]]; then
    echo "Secret value was empty. Skipping add version."
  else
    printf '%s' "$secret_value" | gcloud secrets versions add "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID" --data-file=-
    echo "Added new secret version."
  fi
fi

echo
echo "[4/6] Terraform init..."
cd "$ROOT_DIR/terraform"
terraform init -backend-config="$ROOT_DIR/backend.hcl"

echo
echo "[5/6] Terraform plan..."
terraform plan -var-file="$ROOT_DIR/environment.auto.tfvars"

if [[ "$SKIP_APPLY" == "true" ]]; then
  echo
  echo "[6/6] Apply skipped by --skip-apply."
  exit 0
fi

echo
echo "[6/6] Terraform apply..."
if [[ "$AUTO_APPROVE" == "true" ]]; then
  terraform apply -auto-approve -var-file="$ROOT_DIR/environment.auto.tfvars"
else
  terraform apply -var-file="$ROOT_DIR/environment.auto.tfvars"
fi

echo
echo "Deployment complete."
if terraform output cloud_run_url >/dev/null 2>&1; then
  cloud_run_url="$(terraform output -raw cloud_run_url)"
  echo "Cloud Run URL: $cloud_run_url"
  echo "Set this into apps-script/script-properties.json: CLOUD_RUN_EXECUTE_URL"
fi
