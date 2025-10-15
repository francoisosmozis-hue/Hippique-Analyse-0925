#!/usr/bin/env bash
# Create Cloud Scheduler job for daily 09:00 planning

set -euo pipefail

# Configuration
PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-hippique-orchestrator}"
SA_EMAIL="${SA_EMAIL:-}"
JOB_NAME="${JOB_NAME:-hippique-daily-planning}"

# Validation
if [ -z "$PROJECT_ID" ]; then
  echo "❌ ERROR: PROJECT_ID not set"
  exit 1
fi

if [ -z "$SA_EMAIL" ]; then
  echo "❌ ERROR: SA_EMAIL not set (required for OIDC authentication)"
  exit 1
fi

# Get service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --format 'value(status.url)' 2>/dev/null || echo "")

if [ -z "$SERVICE_URL" ]; then
  echo "❌ ERROR: Service $SERVICE_NAME not found. Deploy it first."
  exit 1
fi

SCHEDULE_URL="${SERVICE_URL}/schedule"

echo "📅 Creating Cloud Scheduler job for daily planning"
echo "   Job: $JOB_NAME"
echo "   Schedule: 09:00 Europe/Paris"
echo "   Target: $SCHEDULE_URL"

# Check if job already exists
if gcloud scheduler jobs describe "$JOB_NAME" \
     --location "$REGION" \
     --project "$PROJECT_ID" &>/dev/null; then
  echo "⚠️  Job $JOB_NAME already exists. Deleting..."
  gcloud scheduler jobs delete "$JOB_NAME" \
    --location "$REGION" \
    --project "$PROJECT_ID" \
    --quiet
fi

# Create the job
gcloud scheduler jobs create http "$JOB_NAME" \
  --location "$REGION" \
  --project "$PROJECT_ID" \
  --schedule "0 9 * * *" \
  --time-zone "Europe/Paris" \
  --uri "$SCHEDULE_URL" \
  --http-method POST \
  --message-body '{"date":"today","mode":"tasks"}' \
  --headers "Content-Type=application/json" \
  --oidc-service-account-email "$SA_EMAIL" \
  --oidc-token-audience "$SERVICE_URL"

echo ""
echo "✅ Scheduler job created successfully!"
echo ""
echo "Details:"
gcloud scheduler jobs describe "$JOB_NAME" \
  --location "$REGION" \
  --project "$PROJECT_ID"

echo ""
echo "To run manually:"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$PROJECT_ID"
echo ""
echo "To view logs:"
echo "  gcloud scheduler jobs logs read $JOB_NAME --location=$REGION --project=$PROJECT_ID --limit=50"
