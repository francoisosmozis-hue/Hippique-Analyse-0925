#!/bin/bash
<<<<<<< HEAD
# scripts/deploy_cloud_run.sh - Déploiement Cloud Run
=======
# scripts/deploy_cloud_run.sh - Deploy Hippique Orchestrator to Cloud Run
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

# Variables optionnelles
GCS_BUCKET="${GCS_BUCKET:-}"
GCS_PREFIX="${GCS_PREFIX:-prod}"
=======
# Load .env file
if [ -f .env ]; then
    set -a; source .env; set +a
fi

# Required variables
PROJECT_ID="${PROJECT_ID:?PROJECT_ID is required}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-hippique-orchestrator}"
SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_EMAIL:-${SERVICE_NAME}@${PROJECT_ID}.iam.gserviceaccount.com}"

# Optional variables
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
MEMORY="${MEMORY:-2Gi}"
CPU="${CPU:-1}"
TIMEOUT="${TIMEOUT:-600}"
MAX_INSTANCES="${MAX_INSTANCES:-10}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
<<<<<<< HEAD

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
=======
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
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
    exit 1
fi

# Set project
gcloud config set project "$PROJECT_ID"

<<<<<<< HEAD
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
=======
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

    echo "  - Using Cloud Build..."
    gcloud builds submit \
        --tag "$IMAGE_TAG" \
        --project="$PROJECT_ID" \
        --timeout=20m

echo "✅ Image built: $IMAGE_TAG"

# ============================================
# Create Cloud Tasks Queue if needed
# ============================================

echo ""
echo "📋 Checking Cloud Tasks Queue..."
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)

if ! gcloud tasks queues describe "$QUEUE_ID" \
    --location="$REGION" \
    --project="$PROJECT_ID" &> /dev/null; then
    
<<<<<<< HEAD
    echo "  - Création de la queue Cloud Tasks..."
=======
    echo "  - Creating queue..."
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
    gcloud tasks queues create "$QUEUE_ID" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --max-concurrent-dispatches=10 \
<<<<<<< HEAD
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
=======
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
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
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
<<<<<<< HEAD
    --set-env-vars="PROJECT_ID=$PROJECT_ID,REGION=$REGION,SERVICE_NAME=$SERVICE_NAME,QUEUE_ID=$QUEUE_ID,SERVICE_ACCOUNT_EMAIL=$SERVICE_ACCOUNT_EMAIL,TZ=Europe/Paris"
)

# Ajouter GCS_BUCKET si défini
=======
    --set-env-vars="PROJECT_ID=$PROJECT_ID,REGION=$REGION,SERVICE_NAME=$SERVICE_NAME,QUEUE_ID=$QUEUE_ID,SERVICE_ACCOUNT_EMAIL=$SERVICE_ACCOUNT_EMAIL,TZ=Europe/Paris,REQUIRE_AUTH=true"
)

# Add GCS variables if configured
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
if [ -n "$GCS_BUCKET" ]; then
    DEPLOY_CMD+=(--set-env-vars="GCS_BUCKET=$GCS_BUCKET,GCS_PREFIX=$GCS_PREFIX")
fi

<<<<<<< HEAD
# Exécuter le déploiement
"${DEPLOY_CMD[@]}"

# ============================================
# Configurer IAM
# ============================================

echo ""
echo "🔐 Configuration IAM..."

# Permettre au service account d'invoquer le service
=======
# Execute deployment
"${DEPLOY_CMD[@]}"

# ============================================
# Configure IAM
# ============================================

echo ""
echo "🔐 Configuring IAM..."

# Allow service account to invoke service
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/run.invoker"

<<<<<<< HEAD
# Permettre à Cloud Tasks d'invoquer le service
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
    --role="roles/run.invoker"

# ============================================
# Récupérer l'URL du service
=======
echo "✅ IAM configured"

# ============================================
# Get service URL
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
# ============================================

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.url)")

echo ""
<<<<<<< HEAD
echo "✅ Déploiement réussi!"
echo "================================================"
echo "Service URL: $SERVICE_URL"
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
=======
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
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
