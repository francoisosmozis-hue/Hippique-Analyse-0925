#!/usr/bin/env bash
# Setup GCP resources for Hippique Orchestrator

set -euo pipefail

# Configuration
PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-europe-west1}"
SA_NAME="${SA_NAME:-hippique-sa}"
BUCKET_NAME="${BUCKET_NAME:-}"

# Validation
if [ -z "$PROJECT_ID" ]; then
  echo "❌ ERROR: PROJECT_ID not set"
  echo "Usage: PROJECT_ID=your-project ./scripts/setup_gcp.sh"
  exit 1
fi

if [ -z "$BUCKET_NAME" ]; then
  echo "❌ ERROR: BUCKET_NAME not set"
  echo "Usage: BUCKET_NAME=your-bucket ./scripts/setup_gcp.sh"
  exit 1
fi

echo "🔧 Setting up GCP resources"
echo "   Project: $PROJECT_ID"
echo "   Region: $REGION"
echo ""

# Set project
gcloud config set project "$PROJECT_ID"

# Enable APIs
echo "📡 Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com

echo "✅ APIs enabled"
echo ""

# Create service account
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" &>/dev/null; then
  echo "ℹ️  Service account $SA_EMAIL already exists"
else
  echo "👤 Creating service account..."
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name "Hippique Orchestrator Service Account" \
    --project "$PROJECT_ID"
  echo "✅ Service account created: $SA_EMAIL"
fi

echo ""

# Grant IAM roles
echo "🔐 Granting IAM roles..."

ROLES=(
  "roles/run.invoker"
  "roles/cloudtasks.enqueuer"
  "roles/storage.objectAdmin"
  "roles/logging.logWriter"
)

for ROLE in "${ROLES[@]}"; do
  echo "   → $ROLE"
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${SA_EMAIL}" \
    --role "$ROLE" \
    --condition None \
    --quiet >/dev/null
done

echo "✅ IAM roles granted"
echo ""

# Create GCS bucket
if gsutil ls -p "$PROJECT_ID" "gs://${BUCKET_NAME}" &>/dev/null; then
  echo "ℹ️  Bucket gs://${BUCKET_NAME} already exists"
else
  echo "🪣 Creating GCS bucket..."
  gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://${BUCKET_NAME}"
  echo "✅ Bucket created: gs://${BUCKET_NAME}"
fi

echo ""

# Create Cloud Tasks queue
QUEUE_NAME="hippique-tasks"
if gcloud tasks queues describe "$QUEUE_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
  echo "ℹ️  Queue $QUEUE_NAME already exists"
else
  echo "📋 Creating Cloud Tasks queue..."
  gcloud tasks queues create "$QUEUE_NAME" \
    --location "$REGION" \
    --project "$PROJECT_ID"
  echo "✅ Queue created: $QUEUE_NAME"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Configuration summary:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PROJECT_ID=$PROJECT_ID"
echo "REGION=$REGION"
echo "SERVICE_ACCOUNT=$SA_EMAIL"
echo "GCS_BUCKET=$BUCKET_NAME"
echo "QUEUE_ID=$QUEUE_NAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo "1. Update .env with these values"
echo "2. Run: ./scripts/deploy_cloud_run.sh"
echo "3. Run: ./scripts/create_scheduler_0900.sh"
