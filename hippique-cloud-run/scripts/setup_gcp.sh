#!/bin/bash
set -euo pipefail

echo "🏇 Configuration GCP pour Hippique Analyzer"
echo ""

# Charger variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
else
    echo "❌ .env not found! Copy .env.example first."
    exit 1
fi

echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo ""

# Activer APIs
echo "Activating APIs..."
gcloud services enable             run.googleapis.com             cloudtasks.googleapis.com             cloudscheduler.googleapis.com             storage-api.googleapis.com             --project=$PROJECT_ID

# Service Account
echo "Creating service account..."
gcloud iam service-accounts create scheduler             --display-name="Hippique Scheduler"             --project=$PROJECT_ID || echo "SA already exists"

# Permissions
echo "Setting permissions..."
gcloud projects add-iam-policy-binding $PROJECT_ID             --member="serviceAccount:${SCHEDULER_SA_EMAIL}"             --role="roles/cloudtasks.enqueuer"

gcloud projects add-iam-policy-binding $PROJECT_ID             --member="serviceAccount:${SCHEDULER_SA_EMAIL}"             --role="roles/run.invoker"

# Cloud Tasks Queue
echo "Creating Cloud Tasks queue..."
gcloud tasks queues create $QUEUE_ID             --location=$REGION             --project=$PROJECT_ID || echo "Queue already exists"

echo ""
echo "✅ GCP setup complete!"
echo "Next: ./scripts/deploy_cloud_run.sh"
