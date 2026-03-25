#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="${1:-$ROOT_DIR/saas.env}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Config file not found: $CONFIG_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$CONFIG_FILE"
set +a

required=(TOOL_PROJECT_ID TFSTATE_BUCKET TFSTATE_LOCATION)
for key in "${required[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    echo "Missing required key in $CONFIG_FILE: $key" >&2
    exit 1
  fi
done

echo "Creating tfstate bucket if missing: gs://$TFSTATE_BUCKET"
if ! gcloud storage buckets describe "gs://$TFSTATE_BUCKET" --project "$TOOL_PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$TFSTATE_BUCKET" \
    --project "$TOOL_PROJECT_ID" \
    --location "$TFSTATE_LOCATION" \
    --uniform-bucket-level-access
fi

gcloud storage buckets update "gs://$TFSTATE_BUCKET" \
  --project "$TOOL_PROJECT_ID" \
  --versioning

echo "tfstate bucket ready: gs://$TFSTATE_BUCKET (versioning enabled)"
