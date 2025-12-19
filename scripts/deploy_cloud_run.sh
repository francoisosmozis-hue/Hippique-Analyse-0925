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

QUEUE_ID="${QUEUE_ID:-hippique-tasks}"

if ! gcloud tasks queues describe "$QUEUE_ID" \
    --location="$REGION" \
    --project="$PROJECT_ID" &> /dev/null; then
    
    echo "  - Création de la queue Cloud Tasks..."
    gcloud tasks queues create "$QUEUE_ID" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --max-concurrent-dispatches=10 \
        --max-dispatches-per-second=5
else
    echo "  - Queue Cloud Tasks existe déjà"
fi

# ============================================
# Déployer le service Cloud Run
# ============================================

echo ""
echo "☁️  Déploiement sur Cloud Run..."

# Construire la commande de déploiement
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
    --allow-unauthenticated # Allow unauthenticated access for public endpoints
)

# Construire la liste des variables d'environnement
ENV_VARS="PROJECT_ID=$PROJECT_ID,REGION=$REGION,SERVICE_NAME=$SERVICE_NAME,QUEUE_ID=$QUEUE_ID,SERVICE_ACCOUNT_EMAIL=$SERVICE_ACCOUNT_EMAIL,TZ=Europe/Paris"
# OIDC_AUDIENCE will be set dynamically after service URL is known

# Ajouter GCS_BUCKET si défini
if [ -n "$GCS_BUCKET" ]; then
    ENV_VARS+=",GCS_BUCKET=$GCS_BUCKET,GCS_PREFIX=$GCS_PREFIX"
fi

DEPLOY_CMD+=(--set-env-vars="$ENV_VARS")

# Exécuter le déploiement
"${DEPLOY_CMD[@]}"

# ============================================
# Configurer IAM
# ============================================

echo ""
echo "🔐 Configuration IAM..."

# Permettre au service account d'invoquer le service
# Note : Le service s'invoque lui-même si create_task utilise le même SA.
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/run.invoker" --quiet

# Le script ajoutait la policy deux fois, une seule suffit.

# ============================================
# Récupérer l'URL du service
# ============================================

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.url)")

echo ""
echo "✅ Déploiement réussi!"
echo "================================================"
echo "Service URL: $SERVICE_URL"

# Update OIDC_AUDIENCE environment variable to match the actual service URL
echo "Updating OIDC_AUDIENCE environment variable to $SERVICE_URL..."
gcloud run services update "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --set-env-vars="OIDC_AUDIENCE=$SERVICE_URL" \
    --quiet
echo "OIDC_AUDIENCE environment variable updated."
echo ""
echo "📝 Prochaines étapes:"
echo "1. Mettre à jour .env avec OIDC_AUDIENCE=$SERVICE_URL"
echo "2. Créer le job Cloud Scheduler:"
echo "   ./scripts/create_scheduler_0900.sh"
echo "3. Tester les endpoints:"
echo "   curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
echo "     -X POST $SERVICE_URL/schedule \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"date\":\"today\",\"mode\":\"tasks\"}'"
echo ""