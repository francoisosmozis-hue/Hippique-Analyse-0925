#!/bin/bash
# scripts/create_scheduler_0900.sh - Create Cloud Scheduler Job (09:00 Paris)

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
SERVICE_URL="${SERVICE_URL:?SERVICE_URL is required - run deploy_cloud_run.sh first}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-${SERVICE_NAME}@${PROJECT_ID}.iam.gserviceaccount.com}"

# Scheduler configuration
JOB_NAME="${JOB_NAME:-hippique-daily-planning}"
SCHEDULE="${SCHEDULE:-0 9 * * *}"  # 09:00 every day
TIMEZONE="${TIMEZONE:-Europe/Paris}"

echo "================================================"
echo "  Cloud Scheduler - Daily Planning Job"
echo "================================================"
echo ""
echo "Project:    $PROJECT_ID"
echo "Region:     $REGION"
echo "Job Name:   $JOB_NAME"
echo "Schedule:   $SCHEDULE ($TIMEZONE)"
echo "Target URL: $SERVICE_URL/schedule"
echo ""

# ============================================
# Verify service is deployed
# ============================================

echo "🔍 Verifying Cloud Run service..."

if ! gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" &> /dev/null; then
    echo "❌ Error: Cloud Run service $SERVICE_NAME not found"
    echo "    Run ./scripts/deploy_cloud_run.sh first"
    exit 1
fi

echo "✅ Service verified"

# ============================================
# Delete existing job if exists
# ============================================

echo ""
echo "🗑️  Checking for existing job..."

if gcloud scheduler jobs describe "$JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" &> /dev/null; then
    
    echo "  - Deleting existing job..."
    gcloud scheduler jobs delete "$JOB_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --quiet
    
    echo "  - Waiting for deletion..."
    sleep 5
fi

echo "✅ Ready to create job"

# ============================================
# Create Cloud Scheduler job
# ============================================

echo ""
echo "📅 Creating Cloud Scheduler job..."

gcloud scheduler jobs create http "$JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri="${SERVICE_URL}/schedule" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{"date":"today","mode":"tasks"}' \
    --oidc-service-account-email="$SERVICE_ACCOUNT_EMAIL" \
    --oidc-token-audience="$SERVICE_URL" \
    --attempt-deadline=600s \
    --max-retry-attempts=3 \
    --max-retry-duration=3600s \
    --min-backoff=30s \
    --max-backoff=300s

echo "✅ Job created"

# ============================================
# Test the job (optional)
# ============================================

echo ""
read -p "🧪 Do you want to test the job now? (y/N) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "🚀 Triggering job manually..."
    
    gcloud scheduler jobs run "$JOB_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID"
    
    echo ""
    echo "📊 Check execution status:"
    echo "   gcloud scheduler jobs describe $JOB_NAME --location=$REGION"
    echo ""
    echo "📋 Check logs:"
    echo "   gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME' --limit=50"
fi

# ============================================
# Summary
# ============================================

echo ""
echo "================================================"
echo "  ✅ Scheduler Job Created Successfully!"
echo "================================================"
echo ""
echo "Job Name:     $JOB_NAME"
echo "Schedule:     $SCHEDULE ($TIMEZONE)"
echo "Next run:     $(date -d 'tomorrow 09:00' '+%Y-%m-%d 09:00' 2>/dev/null || echo 'See Cloud Console')"
echo ""
echo "📝 Management Commands:"
echo ""
echo "# View job details"
echo "gcloud scheduler jobs describe $JOB_NAME --location=$REGION"
echo ""
echo "# View job logs"
echo "gcloud scheduler jobs logs read $JOB_NAME --location=$REGION --limit=50"
echo ""
echo "# Trigger manually"
echo "gcloud scheduler jobs run $JOB_NAME --location=$REGION"
echo ""
echo "# Pause job"
echo "gcloud scheduler jobs pause $JOB_NAME --location=$REGION"
echo ""
echo "# Resume job"
echo "gcloud scheduler jobs resume $JOB_NAME --location=$REGION"
echo ""
echo "# Delete job"
echo "gcloud scheduler jobs delete $JOB_NAME --location=$REGION"
echo ""
echo "================================================"
