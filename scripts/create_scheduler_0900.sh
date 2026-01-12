#!/bin/bash
# scripts/create_scheduler_0900.sh - Créer le job Cloud Scheduler quotidien

set -euo pipefail

# ============================================
# Configuration
# ============================================

# Charger .env si présent
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Variables obligatoires
PROJECT_ID="${PROJECT_ID:-}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-hippique-orchestrator}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-}"
INTERNAL_API_SECRET="${INTERNAL_API_SECRET:-}"

if [ -z "$PROJECT_ID" ]; then
    echo "❌ PROJECT_ID is required"
    exit 1
fi

if [ -z "$INTERNAL_API_SECRET" ]; then
    echo "❌ INTERNAL_API_SECRET is required"
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
if gcloud scheduler jobs describe "$JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" &> /dev/null; then
    
    echo "⚠️  Job existant trouvé, mise à jour..."
    
    gcloud scheduler jobs update http "$JOB_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="$SCHEDULE" \
        --time-zone="$TIMEZONE" \
        --uri="${SERVICE_URL}/schedule" \
        --http-method=POST \
        --oidc-service-account-email="" \
        --update-headers="Content-Type=application/json,X-API-KEY=${INTERNAL_API_SECRET}" \
        --message-body="$PAYLOAD" \
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
        --headers="Content-Type=application/json,X-API-KEY=${INTERNAL_API_SECRET}" \
        --message-body="$PAYLOAD" \
        --description="$DESCRIPTION"
fi

# ============================================
# Tester le job manuellement (optionnel)
# ============================================

echo ""
read -p "🧪 Voulez-vous tester le job immédiatement ? (y/N) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "⚙️  Exécution du job de test..."
    
    gcloud scheduler jobs run "$JOB_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID"
    
    echo ""
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