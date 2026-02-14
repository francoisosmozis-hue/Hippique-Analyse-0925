#!/bin/bash
# scripts/deploy_cloud_run.sh - Déploiement Cloud Run

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

if [ -z "$PROJECT_ID" ]; then
    echo "❌ PROJECT_ID is required"
    exit 1
fi

if [ -z "$SERVICE_ACCOUNT_EMAIL" ]; then
    echo "❌ SERVICE_ACCOUNT_EMAIL is required"
    exit 1
fi

# Variables optionnelles
GCS_BUCKET="${GCS_BUCKET:-}"
GCS_PREFIX="${GCS_PREFIX:-prod}"
MEMORY="${MEMORY:-2Gi}"
CPU="${CPU:-1}"
TIMEOUT="${TIMEOUT:-600}"
MAX_INSTANCES="${MAX_INSTANCES:-10}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"

echo "🚀 Déploiement de $SERVICE_NAME sur Cloud Run"
echo "================================================"
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Service Account: $SERVICE_ACCOUNT_EMAIL"
echo "Memory: $MEMORY"
echo "CPU: $CPU"
echo "Timeout: ${TIMEOUT}s"
echo ""

# ============================================
# Vérifications préalables
# ============================================

echo "🔍 Vérification des prérequis..."

# Vérifier gcloud
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI n'est pas installé"
    exit 1
fi

# Vérifier Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker n'est pas installé"
    exit 1
fi

# Vérifier que le projet existe
if ! gcloud projects describe "$PROJECT_ID" &> /dev/null; then
    echo "❌ Projet $PROJECT_ID introuvable"
    exit 1
fi

# Set project
gcloud config set project "$PROJECT_ID"

# ============================================
# Activer les APIs nécessaires
# ============================================

echo ""
echo "🔧 Activation des APIs GCP..."

APIS=(
    "run.googleapis.com"
    "cloudtasks.googleapis.com"
    "cloudscheduler.googleapis.com"
    "cloudbuild.googleapis.com"
    "artifactregistry.googleapis.com"
)

for api in "${APIS[@]}"; do
    echo "  - Activation de $api..."
    gcloud services enable "$api" --project="$PROJECT_ID" --quiet
done

# ============================================
# Créer Artifact Registry si nécessaire
# ============================================

echo ""
echo "📦 Vérification Artifact Registry..."

REPO_NAME="hippique-images"
REPO_LOCATION="$REGION"

if ! gcloud artifacts repositories describe "$REPO_NAME" \
    --location="$REPO_LOCATION" \
    --project="$PROJECT_ID" &> /dev/null; then
    
    echo "  - Création du repository Artifact Registry..."
    gcloud artifacts repositories create "$REPO_NAME" \
        --repository-format=docker \
        --location="$REPO_LOCATION" \
        --description="Hippique Orchestrator images" \
        --project="$PROJECT_ID"
else
    echo "  - Repository Artifact Registry existe déjà"
fi

# ============================================
# Build et push de l'image
# ============================================

echo ""
echo "🏗️  Build de l'image Docker..."

IMAGE_TAG="${REPO_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest"

# Configure Docker auth pour Artifact Registry
gcloud auth configure-docker "${REPO_LOCATION}-docker.pkg.dev" --quiet

# Build avec Cloud Build (recommandé) ou Docker local
USE_CLOUD_BUILD="${USE_CLOUD_BUILD:-true}"

if [ "$USE_CLOUD_BUILD" = "true" ]; then
    echo "  - Build avec Cloud Build..."
    gcloud builds submit \
        --tag="$IMAGE_TAG" \
        --project="$PROJECT_ID" \
        --timeout=20m \
        .
else
    echo "  - Build local avec Docker..."
    docker build -t "$IMAGE_TAG" .
    docker push "$IMAGE_TAG"
fi

echo "✅ Image construite: $IMAGE_TAG"

# ============================================
# Créer Cloud Tasks Queue si nécessaire
# ============================================

echo ""
echo "📋 Vérification Cloud Tasks Queue..."

QUEUE_ID="${QUEUE_ID:-hippique-tasks-v2}" # Default to v2

if ! gcloud tasks queues describe "$QUEUE_ID" \
    --location="$REGION" \
    --project="$PROJECT_ID" &> /dev/null; then
    
    echo "  - Création de la queue Cloud Tasks..."
    gcloud tasks queues create "$QUEUE_ID" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --max-concurrent-dispatches=1000 \
        --max-dispatches-per-second=500
else
    echo "  - Queue Cloud Tasks existe déjà"
fi

# ============================================
# Déployer le service Cloud Run
# ============================================

echo ""
echo "☁️  Déploiement sur Cloud Run..."

# Générer une clé secrète si elle n'est pas déjà dans l'environnement
INTERNAL_API_SECRET="${INTERNAL_API_SECRET:-$(openssl rand -hex 16)}"

# Construire les variables d'environnement
ENV_VARS="PROJECT_ID=$PROJECT_ID"
ENV_VARS+=",LOCATION=$REGION"
ENV_VARS+=",BUCKET_NAME=${GCS_BUCKET:-}"
ENV_VARS+=",TASK_QUEUE=${QUEUE_ID:-hippique-tasks-v2}"
ENV_VARS+=",FIRESTORE_COLLECTION=${FIRESTORE_COLLECTION:-races-prod}"

# Déployer le service en mode public avec la clé secrète
gcloud run deploy "$SERVICE_NAME" \
    --image="$IMAGE_TAG" \
    --platform=managed \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --service-account="$SERVICE_ACCOUNT_EMAIL" \
    --memory="$MEMORY" \
    --cpu="$CPU" \
    --timeout="${TIMEOUT}s" \
    --max-instances="$MAX_INSTANCES" \
    --min-instances="$MIN_INSTANCES" \
    --allow-unauthenticated \
    --set-env-vars="$ENV_VARS" \
    --quiet

echo "✅ Déploiement terminé."

# ============================================
# Finalisation
# ============================================

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --project="$PROJECT_ID" --format="value(status.url)")

echo ""
echo "🎉 Déploiement terminé avec succès!"
echo "================================================"
echo "Service URL: $SERVICE_URL"
echo "Clé API interne: ${INTERNAL_API_SECRET}"
echo ""
echo "📝 Prochaines étapes:"
echo "1. Mettre à jour le Cloud Scheduler pour inclure la clé secrète dans les appels."
echo "2. Tester la création de tâches via le endpoint /schedule:"
echo "   curl -X POST \"${SERVICE_URL}/schedule\" -H \"X-API-KEY: ${INTERNAL_API_SECRET}\" -H \"Content-Type: application/json\" -d '{\"force\": true}'"
echo ""