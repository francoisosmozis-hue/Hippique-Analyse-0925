#!/bin/bash
set -e

# ============================================================================
# Création du job Cloud Scheduler quotidien à 09:00 Europe/Paris
# ============================================================================
# Usage: ./create_scheduler_0900.sh
# ============================================================================

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}⏰ Configuration Cloud Scheduler - Déclenchement quotidien${NC}"
echo "=============================================="

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
if [ -f .env ]; then
    echo -e "${GREEN}📄 Chargement .env${NC}"
    export $(cat .env | grep -v '^#' | xargs)
fi

PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project)}
REGION=${REGION:-"europe-west1"}
SERVICE_NAME=${SERVICE_NAME:-"horse-racing-orchestrator"}
SA_EMAIL=${SA_EMAIL:-"${SERVICE_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"}
JOB_NAME=${SCHEDULER_JOB_0900:-"daily-plan-0900"}
SCHEDULE_TIME=${DAILY_SCHEDULE_HOUR:-"9"}

# Vérifications
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}❌ PROJECT_ID non défini${NC}"
    exit 1
fi

if [ -z "$SERVICE_URL" ]; then
    echo -e "${YELLOW}⚠️  SERVICE_URL non défini, récupération...${NC}"
    SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
        --region ${REGION} \
        --project ${PROJECT_ID} \
        --format 'value(status.url)')
    
    if [ -z "$SERVICE_URL" ]; then
        echo -e "${RED}❌ Impossible de récupérer SERVICE_URL. Le service Cloud Run est-il déployé ?${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo "  Project ID: ${PROJECT_ID}"
echo "  Region: ${REGION}"
echo "  Job Name: ${JOB_NAME}"
echo "  Schedule: ${SCHEDULE_TIME}:00 Europe/Paris (tous les jours)"
echo "  Target URL: ${SERVICE_URL}/schedule"
echo "  Service Account: ${SA_EMAIL}"
echo ""

# ----------------------------------------------------------------------------
# Vérification de l'API Cloud Scheduler
# ----------------------------------------------------------------------------
echo -e "${BLUE}🔍 Vérification de l'API Cloud Scheduler...${NC}"

if ! gcloud services list --enabled --project=${PROJECT_ID} | grep -q cloudscheduler.googleapis.com; then
    echo -e "${YELLOW}Activation de l'API Cloud Scheduler...${NC}"
    gcloud services enable cloudscheduler.googleapis.com --project=${PROJECT_ID}
    echo -e "${GREEN}✅ API activée${NC}"
    
    # Attendre que l'API soit prête
    echo "Attente de la propagation de l'API (30s)..."
    sleep 30
else
    echo -e "${GREEN}✅ API déjà activée${NC}"
fi

# ----------------------------------------------------------------------------
# Création/Mise à jour du job
# ----------------------------------------------------------------------------
echo ""
echo -e "${BLUE}📅 Configuration du job Scheduler...${NC}"

# Construire le cron expression
CRON_SCHEDULE="0 ${SCHEDULE_TIME} * * *"
TIMEZONE="Europe/Paris"

# Payload JSON
PAYLOAD='{
  "date": "today",
  "mode": "tasks"
}'

# Vérifier si le job existe
JOB_EXISTS=$(gcloud scheduler jobs list \
    --location=${REGION} \
    --project=${PROJECT_ID} \
    --filter="name:${JOB_NAME}" \
    --format="value(name)" | wc -l)

if [ "$JOB_EXISTS" -gt 0 ]; then
    echo -e "${YELLOW}⚠️  Le job existe déjà, mise à jour...${NC}"
    
    gcloud scheduler jobs update http ${JOB_NAME} \
        --location=${REGION} \
        --project=${PROJECT_ID} \
        --schedule="${CRON_SCHEDULE}" \
        --time-zone="${TIMEZONE}" \
        --uri="${SERVICE_URL}/schedule" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="${PAYLOAD}" \
        --oidc-service-account-email=${SA_EMAIL} \
        --oidc-token-audience=${SERVICE_URL}
    
    echo -e "${GREEN}✅ Job mis à jour${NC}"
else
    echo -e "${YELLOW}Création du job...${NC}"
    
    gcloud scheduler jobs create http ${JOB_NAME} \
        --location=${REGION} \
        --project=${PROJECT_ID} \
        --schedule="${CRON_SCHEDULE}" \
        --time-zone="${TIMEZONE}" \
        --uri="${SERVICE_URL}/schedule" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="${PAYLOAD}" \
        --oidc-service-account-email=${SA_EMAIL} \
        --oidc-token-audience=${SERVICE_URL}
    
    echo -e "${GREEN}✅ Job créé${NC}"
fi

# ----------------------------------------------------------------------------
# Test manuel (optionnel)
# ----------------------------------------------------------------------------
echo ""
echo -e "${BLUE}🧪 Test du job (exécution manuelle)...${NC}"
read -p "Voulez-vous tester le job maintenant ? (y/N) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Déclenchement manuel...${NC}"
    
    gcloud scheduler jobs run ${JOB_NAME} \
        --location=${REGION} \
        --project=${PROJECT_ID}
    
    echo -e "${GREEN}✅ Job déclenché${NC}"
    echo ""
    echo -e "${YELLOW}📊 Vérifiez les logs:${NC}"
    echo "   gcloud logging read \"resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE_NAME}\" \\"
    echo "       --limit 50 --format json --project=${PROJECT_ID}"
else
    echo -e "${YELLOW}⏭️  Test skippé${NC}"
fi

# ----------------------------------------------------------------------------
# Résumé
# ----------------------------------------------------------------------------
echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}✅ SCHEDULER CONFIGURÉ${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "${YELLOW}📋 Détails du job:${NC}"
echo "   Nom: ${JOB_NAME}"
echo "   Planification: Tous les jours à ${SCHEDULE_TIME}:00 ${TIMEZONE}"
echo "   Prochaine exécution: $(gcloud scheduler jobs describe ${JOB_NAME} --location=${REGION} --project=${PROJECT_ID} --format='value(schedule)' 2>/dev/null || echo 'N/A')"
echo "   Target: ${SERVICE_URL}/schedule"
echo ""
echo -e "${YELLOW}🔍 Commandes utiles:${NC}"
echo "   # Voir les détails du job"
echo "   gcloud scheduler jobs describe ${JOB_NAME} --location=${REGION}"
echo ""
echo "   # Lister tous les jobs"
echo "   gcloud scheduler jobs list --location=${REGION}"
echo ""
echo "   # Déclencher manuellement"
echo "   gcloud scheduler jobs run ${JOB_NAME} --location=${REGION}"
echo ""
echo "   # Voir les logs d'exécution"
echo "   gcloud logging read \"resource.type=cloud_scheduler_job\" --limit 10"
echo ""
echo "   # Supprimer le job"
echo "   gcloud scheduler jobs delete ${JOB_NAME} --location=${REGION}"
echo ""
echo -e "${GREEN}🐴 Le plan sera généré automatiquement chaque jour à ${SCHEDULE_TIME}h !${NC}"
