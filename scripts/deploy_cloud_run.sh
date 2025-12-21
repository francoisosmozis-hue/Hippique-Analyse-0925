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

# Construire la liste des variables d'environnement connues à l'avance
# OIDC_AUDIENCE et CLOUD_RUN_URL seront ajoutées dans une étape ultérieure
ENV_VARS="PROJECT_ID=$PROJECT_ID"
ENV_VARS+=",REGION=$REGION"
ENV_VARS+=",SERVICE_NAME=$SERVICE_NAME"
ENV_VARS+=",QUEUE_ID=${QUEUE_ID:-hippique-tasks-v2}"
ENV_VARS+=",SERVICE_ACCOUNT_EMAIL=$SERVICE_ACCOUNT_EMAIL"
ENV_VARS+=",TZ=Europe/Paris"
ENV_VARS+=",USE_FIRESTORE=True"
ENV_VARS+=",USE_GCS=True"
ENV_VARS+=",REQUIRE_AUTH=True"
ENV_VARS+=",DEBUG=True"
ENV_VARS+=",BUDGET_TOTAL=5"

if [ -n "$GCS_BUCKET" ]; then
    ENV_VARS+=",GCS_BUCKET=$GCS_BUCKET,GCS_PREFIX=$GCS_PREFIX"
fi

# Déployer le service avec les variables d'environnement initiales
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

echo "✅ Déploiement initial terminé."

# ============================================
# Mise à jour avec l'URL Canonique
# ============================================

echo ""
echo "🔗 Récupération de l'URL canonique et mise à jour de l'audience OIDC..."

# Attendre un court instant pour s'assurer que l'état du service est propagé
sleep 5

# Récupérer l'URL canonique (status.url), qui est la seule audience valide pour OIDC
CANONICAL_SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.url)")

if [ -z "$CANONICAL_SERVICE_URL" ]; then
    echo "❌ Échec de la récupération de l'URL canonique du service. Abandon."
    exit 1
fi

echo "  - URL Canonique (Audience OIDC): $CANONICAL_SERVICE_URL"

# Mettre à jour le service avec les variables d'environnement dépendantes de l'URL
gcloud run services update "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --update-env-vars="OIDC_AUDIENCE=$CANONICAL_SERVICE_URL,CLOUD_RUN_URL=$CANONICAL_SERVICE_URL" \
    --quiet

echo "✅ Variables d'environnement OIDC_AUDIENCE et CLOUD_RUN_URL mises à jour."

# ============================================
# Configurer IAM
# ============================================

echo ""
echo "🔐 Configuration IAM..."

# Permettre au compte de service d'invoquer le service (pour Cloud Tasks)
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/run.invoker" --quiet > /dev/null

echo "✅ Rôle roles/run.invoker ajouté pour le compte de service."

# ============================================
# Finalisation
# ============================================

echo ""
echo "🎉 Déploiement terminé avec succès!"
echo "================================================"
echo "Service URL: $CANONICAL_SERVICE_URL"
echo ""
echo "📝 Prochaines étapes:"
echo "1. (Optionnel) Mettre à jour .env avec OIDC_AUDIENCE=$CANONICAL_SERVICE_URL"
echo "2. Créer le job Cloud Scheduler si ce n'est pas déjà fait:"
echo "   ./scripts/create_scheduler_0900.sh"
echo "3. Tester la création de tâches via le endpoint /schedule:"
echo "   curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token --impersonate-service-account=$SERVICE_ACCOUNT_EMAIL --audiences=$CANONICAL_SERVICE_URL)\" \\"
echo "     -X POST \"$CANONICAL_SERVICE_URL/schedule\" \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     -d '{\"date\":\"today\",\"mode\":\"tasks\"}'"
echo ""