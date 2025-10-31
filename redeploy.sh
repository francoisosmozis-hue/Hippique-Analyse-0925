#!/usr/bin/env bash
set -euo pipefail

# ====== PARAMÈTRES ======
SERVICE="${SERVICE:-hippique-orchestrator}"
REGION="${REGION:-europe-west4}"
PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
PORT="${PORT:-8080}"
TZ="${TZ:-Europe/Paris}"

if [[ -z "$PROJECT" ]]; then
  echo ">> Erreur: aucun projet gcloud actif. Faites: gcloud config set project <PROJECT_ID>"
  exit 1
fi

echo ">> Projet : $PROJECT"
echo ">> Service: $SERVICE"
echo ">> Région : $REGION"

# ====== PRÉ-CHECKS ======
echo ">> Vérif gcloud auth…"
gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q . || {
  echo ">> Pas d'auth active. Lancez: gcloud auth login"
  exit 1
}

# Facultatif: nettoyage cache build local pour éviter 'no space left'
echo ">> Nettoyage caches locaux (optionnel)…"
rm -rf ~/.cache/pip ~/.cache/google-cloud-tools-java 2>/dev/null || true

# ====== DÉPLOIEMENT (Cloud Run 2nd gen) ======
echo ">> Déploiement Cloud Run…"
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars TZ="$TZ" \
  --port "$PORT" \
  --cpu 1 --memory 512Mi \
  --timeout 900 \
  --concurrency 20 \
  --min-instances 0 --max-instances 3

# ====== RÉCUP URL ======
SERVICE_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
if [[ -z "$SERVICE_URL" ]]; then
  echo ">> Erreur: URL de service introuvable."
  exit 1
fi
echo ">> SERVICE_URL: $SERVICE_URL"

# ====== TESTS SANTÉ ======
echo ">> Test /__health…"
curl -fsS "$SERVICE_URL/__health" && echo -e "\n>> /__health OK"

# ====== TEST PIPELINE (H5) ======
echo ">> Test /pipeline/run (H5)…"
curl -fsS -X POST "$SERVICE_URL/pipeline/run" \
  -H 'content-type: application/json' \
  -d '{"reunion":"R1","course":"C1","phase":"H5","budget":5}' | sed -e 's/.*/>> \0/'

echo ">> OK. Déploiement + fumée terminés."
echo ">> Pour consulter les logs en continu:"
echo "   gcloud logs tail --region '$REGION' --service '$SERVICE'"
