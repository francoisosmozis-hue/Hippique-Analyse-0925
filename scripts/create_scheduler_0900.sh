#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PROJECT_ID:-}" ]]; then
  echo "PROJECT_ID environment variable is required" >&2
  exit 1
fi

if [[ -z "${SERVICE_URL:-}" ]]; then
  if [[ -z "${SERVICE_NAME:-}" || -z "${REGION:-}" ]]; then
    echo "Provide SERVICE_URL or both SERVICE_NAME and REGION" >&2
    exit 1
  fi
  SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --project "${PROJECT_ID}" --region "${REGION}" --format='value(status.url)')
fi

REGION="${REGION:-europe-west1}"
JOB_NAME="${JOB_NAME:-hippique-schedule-0900}"
SA_EMAIL="${SA_EMAIL:-}" # service account used for OIDC token

if [[ -z "${SA_EMAIL}" ]]; then
  echo "SA_EMAIL (service account for OIDC) is required" >&2
  exit 1
fi

PAYLOAD='{"date":"today","mode":"tasks"}'

if gcloud scheduler jobs describe "${JOB_NAME}" --project "${PROJECT_ID}" --location "${REGION}" >/dev/null 2>&1; then
  echo "[scheduler] Job ${JOB_NAME} already exists, updating..."
  gcloud scheduler jobs update http "${JOB_NAME}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --schedule "0 9 * * *" \
    --time-zone "Europe/Paris" \
    --uri "${SERVICE_URL}/schedule" \
    --http-method POST \
    --oidc-service-account-email "${SA_EMAIL}" \
    --oidc-token-audience "${SERVICE_URL}" \
    --headers "Content-Type=application/json" \
    --message-body "${PAYLOAD}"
else
  echo "[scheduler] Creating job ${JOB_NAME}..."
  gcloud scheduler jobs create http "${JOB_NAME}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --schedule "0 9 * * *" \
    --time-zone "Europe/Paris" \
    --uri "${SERVICE_URL}/schedule" \
    --http-method POST \
    --oidc-service-account-email "${SA_EMAIL}" \
    --oidc-token-audience "${SERVICE_URL}" \
    --headers "Content-Type=application/json" \
    --message-body "${PAYLOAD}"
fi

echo "[scheduler] Job configured."
