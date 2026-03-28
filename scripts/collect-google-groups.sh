#!/bin/bash
set -euo pipefail

CLOUD_RUN_URL=""
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --cloud-run-url) CLOUD_RUN_URL="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if [[ -z "$CLOUD_RUN_URL" ]]; then
    echo "Error: --cloud-run-url is required."
    echo "Usage: $0 --cloud-run-url <URL>"
    exit 1
fi

echo "Fetching Scheduler SA email from Terraform outputs..."
SCHEDULER_SA=$(cd terraform && terraform output -raw scheduler_invoker_service_account 2>/dev/null || true)

if [[ -z "$SCHEDULER_SA" ]]; then
    echo "Error: Could not retrieve scheduler_invoker_service_account from Terraform."
    exit 1
fi

echo "Fetching OIDC identity token by impersonating ${SCHEDULER_SA}..."
TOKEN=$(gcloud auth print-identity-token --impersonate-service-account="${SCHEDULER_SA}" --audiences="${CLOUD_RUN_URL}" --include-email)

echo "Triggering job at ${CLOUD_RUN_URL}/collect/groups ..."
curl -s -X POST "${CLOUD_RUN_URL}/collect/groups" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"execution_id": "manual-run"}'
echo ""
