#!/bin/bash
# scripts/deploy_cloud_run.sh - Deploy Hippique Orchestrator to Cloud Run

set -euo pipefail

# ============================================
# Configuration
# ============================================

# Load .env file
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Required variables
PROJECT_ID="${PROJECT_ID:?PROJECT_ID is required}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-hippique-orchestrator}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-${SERVICE_NAME}@${PROJECT_ID}.iam.gserviceaccount.com}"

# Optional variables
MEMORY="${MEMORY:-2Gi}"
CPU="${CPU:-1}"
TIMEOUT="${TIMEOUT:-600}"
MAX_INSTANCES="${MAX_INSTANCES:-10}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
QUEUE_ID="${QUEUE_ID:-hippique-tasks}"
GCS_BUCKET="${GCS_BUCKET:-}"
GCS_PREFIX="${GCS_PREFIX:-prod/snapshots}"

# Image configuration
IMAGE_TAG="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"

echo "================================================"
echo "  Hippique Orchestrator - Cloud Run Deployment"
echo "================================================"
echo ""
echo "Project:        $PROJECT_ID"
echo "Region:         $REGION"
echo "Service:        $SERVICE_NAME"
echo "Service Account: $SERVICE_ACCOUNT_EMAIL"
echo "Image:          $IMAGE_TAG"
echo ""

# ============================================
# Verify gcloud configuration
# ============================================

echo "🔍 Verifying gcloud configuration..."

if ! gcloud projects describe "$PROJECT_ID" &> /dev/null; then
    echo "❌ Error: Project $PROJECT_ID not found or no access"
    exit 1
fi

# Set project
gcloud config set project "$PROJECT_ID"

echo "✅ Project configured"

# ============================================
# Enable required APIs
# ============================================

echo ""
echo "🔌 Enabling required APIs..."

gcloud services enable \
    cloudbuild.googleapis.com \
    run.googleapis.com \
    cloudtasks.googleapis.com \
    cloudscheduler.googleapis.com \
    storage-api.googleapis.com \
    --project="$PROJECT_ID"

echo "✅ APIs enabled"

# ============================================
# Create service account if not exists
# ============================================

echo ""
echo "👤 Checking service account..."

if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT_EMAIL" \
    --project="$PROJECT_ID" &> /dev/null; then
    
    echo "  - Creating service account..."
    gcloud iam service-accounts create "${SERVICE_NAME}" \
        --display-name="Hippique Orchestrator Service Account" \
        --project="$PROJECT_ID"
    
    # Grant necessary roles
    echo "  - Granting IAM roles..."
    
    # Cloud Run invoker (for self-invocation)
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
        --role="roles/run.invoker"
    
    # Cloud Tasks enqueuer
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
        --role="roles/cloudtasks.enqueuer"
    
    # Cloud Storage (if configured)
    if [ -n "$GCS_BUCKET" ]; then
        gcloud projects add-iam-policy-binding "$PROJECT_ID" \
            --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
            --role="roles/storage.objectAdmin"
    fi
    
else
    echo "  - Service account already exists"
fi

echo "✅ Service account ready"

# ============================================
# Build and push Docker image
# ============================================

echo ""
echo "🏗️  Building Docker image..."

if command -v docker &> /dev/null; then
    echo "  - Using local Docker..."
    docker build -t "$IMAGE_TAG" .
    docker push "$IMAGE_TAG"
else
    echo "  - Using Cloud Build..."
    gcloud builds submit \
        --tag "$IMAGE_TAG" \
        --project="$PROJECT_ID" \
        --timeout=20m
fi

echo "✅ Image built: $IMAGE_TAG"

# ============================================
# Create Cloud Tasks Queue if needed
# ============================================

echo ""
echo "📋 Checking Cloud Tasks Queue..."

if ! gcloud tasks queues describe "$QUEUE_ID" \
    --location="$REGION" \
    --project="$PROJECT_ID" &> /dev/null; then
    
    echo "  - Creating queue..."
    gcloud tasks queues create "$QUEUE_ID" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --max-concurrent-dispatches=10 \
        --max-dispatches-per-second=5 \
        --max-attempts=3 \
        --max-retry-duration=3600s
else
    echo "  - Queue already exists"
fi

echo "✅ Queue ready"

# ============================================
# Deploy Cloud Run service
# ============================================

echo ""
echo "☁️  Deploying to Cloud Run..."

# Build deploy command
DEPLOY_CMD=(
    gcloud run deploy "$SERVICE_NAME"
    --image="$IMAGE_TAG"
    --platform=managed
    --region="$REGION"
    --project="$PROJECT_ID"
    --service-account="$SERVICE_ACCOUNT_EMAIL"
    --memory="$MEMORY"
    --cpu="$CPU"
    --timeout="${TIMEOUT}s"
    --max-instances="$MAX_INSTANCES"
    --min-instances="$MIN_INSTANCES"
    --no-allow-unauthenticated
    --set-env-vars="PROJECT_ID=$PROJECT_ID,REGION=$REGION,SERVICE_NAME=$SERVICE_NAME,QUEUE_ID=$QUEUE_ID,SERVICE_ACCOUNT_EMAIL=$SERVICE_ACCOUNT_EMAIL,TZ=Europe/Paris,REQUIRE_AUTH=true"
)

# Add GCS variables if configured
if [ -n "$GCS_BUCKET" ]; then
    DEPLOY_CMD+=(--set-env-vars="GCS_BUCKET=$GCS_BUCKET,GCS_PREFIX=$GCS_PREFIX")
fi

# Execute deployment
"${DEPLOY_CMD[@]}"

# ============================================
# Configure IAM
# ============================================

echo ""
echo "🔐 Configuring IAM..."

# Allow service account to invoke service
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/run.invoker"

echo "✅ IAM configured"

# ============================================
# Get service URL
# ============================================

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.url)")

echo ""
echo "================================================"
echo "  ✅ Deployment Successful!"
echo "================================================"
echo ""
echo "Service URL: $SERVICE_URL"
echo ""
echo "📝 Next Steps:"
echo ""
echo "1. Update .env file:"
echo "   SERVICE_URL=$SERVICE_URL"
echo ""
echo "2. Create Cloud Scheduler job (09:00 daily):"
echo "   ./scripts/create_scheduler_0900.sh"
echo ""
echo "3. Test the service:"
echo "   # Health check"
echo "   curl $SERVICE_URL/healthz"
echo ""
echo "   # Trigger schedule (requires auth)"
echo "   curl -X POST $SERVICE_URL/schedule \\"
echo "     -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"date\":\"today\",\"mode\":\"tasks\"}'"
echo ""
echo "4. Monitor logs:"
echo "   gcloud run services logs tail $SERVICE_NAME --region=$REGION"
echo ""
echo "================================================"
