#!/usr/bin/env bash
set -euo pipefail

# --------- Config de base ----------
PROJECT_ID="$(gcloud config get-value project)"
REGION="europe-west4"
SERVICE="hippique-orchestrator"
TAG="auto-$(date +%Y%m%d-%H%M%S)"
IMAGE="europe-west4-docker.pkg.dev/${PROJECT_ID}/hippique/${SERVICE}:${TAG}"

echo "Project: ${PROJECT_ID}"
echo "Region : ${REGION}"
echo "Service: ${SERVICE}"

# --------- Détection du point d'entrée ----------
ENTRY=""
if [ -f "src/service.py" ]; then
  ENTRY="src.service:app"
  echo "✅ Détecté: src/service.py"
elif [ -f "service.py" ]; then
  ENTRY="service:app"
  echo "✅ Détecté: service.py (racine)"
else
  echo "❌ Introuvable: ni src/service.py ni service.py"
  exit 1
fi

# --------- Vérif requirements ----------
if [ ! -f "requirements.txt" ]; then
  echo "❌ requirements.txt introuvable à la racine"
  exit 1
fi

# --------- Dockerfile (généré automatiquement) ----------
echo "✍️  Génération Dockerfile…"
cat > Dockerfile <<DF
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["uvicorn", "${ENTRY}", "--host", "0.0.0.0", "--port", "8080"]
DF

echo "✅ Dockerfile généré avec ENTRY=${ENTRY}"

# --------- Build image ----------
echo "🔨 gcloud builds submit --tag ${IMAGE}"
gcloud builds submit --tag "${IMAGE}" .

# --------- Deploy (propre) ----------
echo "🚀 Déploiement Cloud Run (image)…"
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --allow-unauthenticated

# --------- Vérifs ----------
SERVICE_URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)')"
echo "🌐 SERVICE_URL=${SERVICE_URL}"

echo "🩺 /__health"
curl -sS "${SERVICE_URL}/__health" || true

echo "📚 /openapi.json (liste des routes)"
curl -sS "${SERVICE_URL}/openapi.json" | jq '.paths | keys' || true

# --------- Conseils si routes manquantes ----------
echo
echo "Tips:"
echo "- Si tu ne vois pas /orchestrate/h5_batch dans la liste des routes:"
echo "  • Vérifie que ta version de src/service.py contient bien ces endpoints."
echo "  • Re-lance ce script depuis la RACINE du repo (où se trouve requirements.txt)."
echo "  • Vérifie qu'aucun autre service.py fantôme n'est copié (./backup_*, ./old/*)."
echo
