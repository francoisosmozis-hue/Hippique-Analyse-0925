#!/bin/bash
set -e

# ============================================================================
# Script de déploiement Cloud Run - Orchestrateur Hippique
# ============================================================================
# Usage: ./deploy_cloud_run.sh [--no-build]
# ============================================================================

# Couleurs pour output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🐴 Déploiement Orchestrateur Hippique Cloud Run${NC}"
echo "=============================================="

# ----------------------------------------------------------------------------
# Configuration (depuis .env ou variables d'environnement)
# ----------------------------------------------------------------------------
if [ -f .env ]; then
    echo -e "${GREEN}📄 Chargement .env${NC}"
    export $(cat .env | grep -v '^#' | xargs)
fi

PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project)}
REGION=${REGION:-"europe-west1"}
SERVICE_NAME=${SERVICE_NAME:-"horse-racing-orchestrator"}
SA_EMAIL=${SA_EMAIL:-"${SERVICE_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"}

# Vérifications
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}❌ PROJECT_ID non défini${NC}"
    exit 1
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project ID: ${PROJECT_ID}"
echo "  Region: ${REGION}"
echo "  Service: ${SERVICE_NAME}"
echo "  Service Account: ${SA_EMAIL}"
echo ""

# ----------------------------------------------------------------------------
# Service Account (création si nécessaire)
# ----------------------------------------------------------------------------
echo -e "${BLUE}🔐 Vérification Service Account...${NC}"

if ! gcloud iam service-accounts describe ${SA_EMAIL} --project=${PROJECT_ID} &>/dev/null; then
    echo -e "${YELLOW}Création du Service Account...${NC}"
    gcloud iam service-accounts create ${SERVICE_NAME} \
        --display-name="Horse Racing Orchestrator" \
        --project=${PROJECT_ID}
    
    # Accorder rôles nécessaires
    echo -e "${YELLOW}Attribution des rôles...${NC}"
    
    # Cloud Run Invoker (pour Scheduler/Tasks)
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/run.invoker"
    
    # Cloud Tasks Enqueuer
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/cloudtasks.enqueuer"
    
    # Storage Object Admin (si GCS utilisé)
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${SA_EMAIL}" \
        --role="roles/storage.objectAdmin"
    
    echo -e "${GREEN}✅ Service Account créé et configuré${NC}"
else
    echo -e "${GREEN}✅ Service Account existe déjà${NC}"
fi

# ----------------------------------------------------------------------------
# Build de l'image (sauf si --no-build)
# ----------------------------------------------------------------------------
if [ "$1" != "--no-build" ]; then
    echo ""
    echo -e "${BLUE}🔨 Build de l'image Docker...${NC}"
    
    IMAGE_URL="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"
    
    gcloud builds submit \
        --tag ${IMAGE_URL} \
        --project=${PROJECT_ID} \
        --timeout=15m
    
    echo -e "${GREEN}✅ Image buildée: ${IMAGE_URL}${NC}"
else
    echo -e "${YELLOW}⏭️  Skip build (--no-build)${NC}"
    IMAGE_URL="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"
fi

# ----------------------------------------------------------------------------
# Déploiement Cloud Run
# ----------------------------------------------------------------------------
echo ""
echo -e "${BLUE}🚀 Déploiement sur Cloud Run...${NC}"

gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_URL} \
    --platform managed \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --service-account ${SA_EMAIL} \
    --no-allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --concurrency 10 \
    --min-instances 0 \
    --max-instances 10 \
    --set-env-vars "PROJECT_ID=${PROJECT_ID},REGION=${REGION},SERVICE_NAME=${SERVICE_NAME},TIMEZONE=Europe/Paris" \
    --set-secrets "GCS_BUCKET=GCS_BUCKET:latest" 2>/dev/null || \
    gcloud run deploy ${SERVICE_NAME} \
    --image ${IMAGE_URL} \
    --platform managed \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --service-account ${SA_EMAIL} \
    --no-allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --concurrency 10 \
    --min-instances 0 \
    --max-instances 10 \
    --set-env-vars "PROJECT_ID=${PROJECT_ID},REGION=${REGION},SERVICE_NAME=${SERVICE_NAME},TIMEZONE=Europe/Paris"

# ----------------------------------------------------------------------------
# Récupération URL et mise à jour IAM
# ----------------------------------------------------------------------------
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --format 'value(status.url)')

echo -e "${GREEN}✅ Service déployé${NC}"
echo -e "${GREEN}   URL: ${SERVICE_URL}${NC}"

# Mettre à jour IAM pour que le SA puisse invoker le service
echo ""
echo -e "${BLUE}🔐 Configuration IAM Invoker...${NC}"
gcloud run services add-iam-policy-binding ${SERVICE_NAME} \
    --region ${REGION} \
    --project ${PROJECT_ID} \
    --member "serviceAccount:${SA_EMAIL}" \
    --role "roles/run.invoker"

echo -e "${GREEN}✅ IAM configuré${NC}"

# ----------------------------------------------------------------------------
# Cloud Tasks Queue (création si nécessaire)
# ----------------------------------------------------------------------------
echo ""
echo -e "${BLUE}📋 Vérification Cloud Tasks Queue...${NC}"

QUEUE_ID=${QUEUE_ID:-"horse-racing-queue"}
QUEUE_PATH="projects/${PROJECT_ID}/locations/${REGION}/queues/${QUEUE_ID}"

if ! gcloud tasks queues describe ${QUEUE_ID} --location=${REGION} --project=${PROJECT_ID} &>/dev/null; then
    echo -e "${YELLOW}Création de la queue...${NC}"
    gcloud tasks queues create ${QUEUE_ID} \
        --location=${REGION} \
        --project=${PROJECT_ID} \
        --max-dispatches-per-second=5 \
        --max-concurrent-dispatches=10 \
        --max-attempts=3
    
    echo -e "${GREEN}✅ Queue créée: ${QUEUE_ID}${NC}"
else
    echo -e "${GREEN}✅ Queue existe déjà: ${QUEUE_ID}${NC}"
fi

# ----------------------------------------------------------------------------
# Test Healthcheck
# ----------------------------------------------------------------------------
echo ""
echo -e "${BLUE}🏥 Test du healthcheck...${NC}"

# Attendre que le service soit prêt
sleep 5

# Obtenir un token d'identité pour tester
TOKEN=$(gcloud auth print-identity-token --audiences=${SERVICE_URL})

HEALTH_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${SERVICE_URL}/healthz")

HTTP_CODE=$(echo "$HEALTH_RESPONSE" | tail -n1)
BODY=$(echo "$HEALTH_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✅ Service en bonne santé${NC}"
    echo "   Response: ${BODY}"
else
    echo -e "${RED}❌ Healthcheck failed (HTTP ${HTTP_CODE})${NC}"
    echo "   Response: ${BODY}"
fi

# ----------------------------------------------------------------------------
# Résumé & Prochaines étapes
# ----------------------------------------------------------------------------
echo ""
echo -e "${BLUE}================================================${NC}"
echo -e "${GREEN}✅ DÉPLOIEMENT TERMINÉ${NC}"
echo -e "${BLUE}================================================${NC}"
echo ""
echo -e "${YELLOW}📝 Informations:${NC}"
echo "   Service URL: ${SERVICE_URL}"
echo "   Service Account: ${SA_EMAIL}"
echo "   Queue: ${QUEUE_ID}"
echo ""
echo -e "${YELLOW}🔄 Prochaines étapes:${NC}"
echo "   1. Mettre à jour .env avec SERVICE_URL=${SERVICE_URL}"
echo "   2. Créer le job Scheduler 09:00:"
echo "      ./scripts/create_scheduler_0900.sh"
echo "   3. Tester manuellement:"
echo "      TOKEN=\$(gcloud auth print-identity-token --audiences=${SERVICE_URL})"
echo "      curl -X POST -H \"Authorization: Bearer \$TOKEN\" \\"
echo "           -H \"Content-Type: application/json\" \\"
echo "           -d '{\"date\":\"today\",\"mode\":\"tasks\"}' \\"
echo "           ${SERVICE_URL}/schedule"
echo ""
echo -e "${GREEN}🐴 Happy racing!${NC}"
