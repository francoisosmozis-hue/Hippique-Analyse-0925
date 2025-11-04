#!/bin/bash
<<<<<<< HEAD
# scripts/create_scheduler_0900.sh - Créer le job Cloud Scheduler quotidien
=======
# scripts/create_scheduler_0900.sh - Create Cloud Scheduler Job (09:00 Paris)
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)

set -euo pipefail

# ============================================
# Configuration
# ============================================

<<<<<<< HEAD
# Charger .env si présent
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Variables obligatoires
PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-hippique-orchestrator}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-}"

if [ -z "$PROJECT_ID" ]; then
    echo "❌ PROJECT_ID is required"
    exit 1
fi

if [ -z "$SERVICE_ACCOUNT_EMAIL" ]; then
    echo "❌ SERVICE_ACCOUNT_EMAIL is required"
    exit 1
fi

# Récupérer l'URL du service Cloud Run
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.url)" 2>/dev/null)

if [ -z "$SERVICE_URL" ]; then
    echo "❌ Service Cloud Run $SERVICE_NAME introuvable"
    echo "   Exécutez d'abord: ./scripts/deploy_cloud_run.sh"
    exit 1
fi

echo "🕐 Création du job Cloud Scheduler quotidien"
echo "================================================"
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Service URL: $SERVICE_URL"
echo "Service Account: $SERVICE_ACCOUNT_EMAIL"
echo ""

# ============================================
# Créer ou mettre à jour le job
# ============================================

JOB_NAME="hippique-daily-planning"
SCHEDULE="0 9 * * *"  # Tous les jours à 09:00 (timezone Europe/Paris)
TIMEZONE="Europe/Paris"
DESCRIPTION="Planification quotidienne des analyses hippiques (H-30 et H-5)"

# Payload JSON pour POST /schedule
PAYLOAD='{
  "date": "today",
  "mode": "tasks"
}'

echo "📋 Configuration du job:"
echo "  Nom: $JOB_NAME"
echo "  Schedule: $SCHEDULE ($TIMEZONE)"
echo "  Endpoint: $SERVICE_URL/schedule"
echo ""

# Vérifier si le job existe déjà
=======
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

>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
if gcloud scheduler jobs describe "$JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" &> /dev/null; then
    
<<<<<<< HEAD
    echo "⚠️  Job existant trouvé, mise à jour..."
    
    gcloud scheduler jobs update http "$JOB_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="$SCHEDULE" \
        --time-zone="$TIMEZONE" \
        --uri="${SERVICE_URL}/schedule" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="$PAYLOAD" \
        --oidc-service-account-email="$SERVICE_ACCOUNT_EMAIL" \
        --oidc-token-audience="$SERVICE_URL" \
        --description="$DESCRIPTION"
    
    echo "✅ Job mis à jour"
else
    echo "🆕 Création du nouveau job..."
    
    gcloud scheduler jobs create http "$JOB_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="$SCHEDULE" \
        --time-zone="$TIMEZONE" \
        --uri="${SERVICE_URL}/schedule" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="$PAYLOAD" \
        --oidc-service-account-email="$SERVICE_ACCOUNT_EMAIL" \
        --oidc-token-audience="$SERVICE_URL" \
        --description="$DESCRIPTION"
    
    echo "✅ Job créé"
fi

# ============================================
# Tester le job manuellement (optionnel)
# ============================================

echo ""
read -p "🧪 Voulez-vous tester le job immédiatement ? (y/N) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "⚙️  Exécution du job de test..."
=======
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
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
    
    gcloud scheduler jobs run "$JOB_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID"
    
    echo ""
<<<<<<< HEAD
    echo "📊 Pour voir les logs:"
    echo "   gcloud logging read 'resource.type=cloud_scheduler_job AND resource.labels.job_id=$JOB_NAME' --limit=20 --format=json"
    echo ""
    echo "   gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME' --limit=50 --format=json"
fi

echo ""
echo "✅ Configuration terminée!"
echo "================================================"
echo ""
echo "📝 Informations du job:"
echo "  Nom: $JOB_NAME"
echo "  Schedule: Tous les jours à 09:00 Europe/Paris"
echo "  Endpoint: POST $SERVICE_URL/schedule"
echo ""
echo "🔍 Commandes utiles:"
echo "  - Voir le job:"
echo "    gcloud scheduler jobs describe $JOB_NAME --location=$REGION"
echo ""
echo "  - Exécuter manuellement:"
echo "    gcloud scheduler jobs run $JOB_NAME --location=$REGION"
echo ""
echo "  - Mettre en pause:"
echo "    gcloud scheduler jobs pause $JOB_NAME --location=$REGION"
echo ""
echo "  - Reprendre:"
echo "    gcloud scheduler jobs resume $JOB_NAME --location=$REGION"
echo ""
echo "  - Supprimer:"
echo "    gcloud scheduler jobs delete $JOB_NAME --location=$REGION"
echo ""
=======
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
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
