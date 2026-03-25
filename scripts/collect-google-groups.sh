#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="$ROOT_DIR/saas.env"
CLOUD_RUN_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cloud-run-url)
      CLOUD_RUN_URL="$2"
      shift 2
      ;;
    --config)
      CONFIG_FILE="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: bash scripts/collect-google-groups.sh --cloud-run-url <url> [--config <saas.env>]
USAGE
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$CLOUD_RUN_URL" ]]; then
  echo "--cloud-run-url is required" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Config file not found: $CONFIG_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$CONFIG_FILE"
set +a

if [[ -z "${TOOL_PROJECT_ID:-}" || -z "${WEBHOOK_SECRET_NAME:-}" ]]; then
  echo "TOOL_PROJECT_ID and WEBHOOK_SECRET_NAME are required in $CONFIG_FILE" >&2
  exit 1
fi

token="$(gcloud secrets versions access latest --secret "$WEBHOOK_SECRET_NAME" --project "$TOOL_PROJECT_ID")"

curl -sS -X POST "${CLOUD_RUN_URL%/}/collect/groups" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: $token" \
  -d '{}'

echo
