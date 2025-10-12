#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${PROJECT_ID:-}" ]]; then
  echo "PROJECT_ID environment variable is required" >&2
  exit 1
fi

REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-hippique-analyse}"
IMAGE="${IMAGE:-gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-}" # optional deployer service account

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI is required" >&2
  exit 1
fi

echo "[deploy] Building container image ${IMAGE}..."
gcloud builds submit --project "${PROJECT_ID}" --tag "${IMAGE}" .

echo "[deploy] Deploying to Cloud Run service ${SERVICE_NAME} in ${REGION}..."
DEPLOY_ARGS=(
  "--project=${PROJECT_ID}"
  "--region=${REGION}"
  "--platform=managed"
  "--image=${IMAGE}"
  "--no-allow-unauthenticated"
  "--port=8080"
  "--memory=1Gi"
  "--cpu=1"
  "--min-instances=0"
  "--max-instances=4"
  "--set-env-vars=TZ=Europe/Paris"
)

if [[ -n "${SERVICE_ACCOUNT}" ]]; then
  DEPLOY_ARGS+=("--service-account=${SERVICE_ACCOUNT}")
fi

gcloud run deploy "${SERVICE_NAME}" "${DEPLOY_ARGS[@]}"

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --project "${PROJECT_ID}" --region "${REGION}" --format='value(status.url)')

echo "[deploy] Service URL: ${SERVICE_URL}"

echo "[deploy] Granting Cloud Run Invoker role to ${SERVICE_ACCOUNT} if provided..."
if [[ -n "${SERVICE_ACCOUNT}" ]]; then
  gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --member "serviceAccount:${SERVICE_ACCOUNT}" \
    --role "roles/run.invoker"
fi

echo "Deployment completed."
