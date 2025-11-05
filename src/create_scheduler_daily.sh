#!/bin/bash
set -e

PROJECT_ID="analyse-hippique"
REGION="europe-west1"
SERVICE_URL="https://hippique-orchestrator-h3tdqmb7jq-ew.a.run.app"
SA_EMAIL="hippique-orchestrator@analyse-hippique.iam.gserviceaccount.com"

echo "=== Création Cloud Scheduler ==="

# Supprimer ancien job si existe
gcloud scheduler jobs delete schedule-hippique-09h \
  --location=$REGION \
  --quiet 2>/dev/null || true

# Créer le job
gcloud scheduler jobs create http schedule-hippique-09h \
  --location=$REGION \
  --schedule="0 9 * * *" \
  --time-zone="Europe/Paris" \
  --uri="$SERVICE_URL/schedule" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body='{"date":"today","mode":"tasks"}' \
  --oidc-service-account-email=$SA_EMAIL \
  --oidc-token-audience=$SERVICE_URL

echo "✅ Scheduler créé : Tous les jours à 09:00 Europe/Paris"

# Test immédiat
echo -e "\n=== Test du scheduler (exécution manuelle) ==="
gcloud scheduler jobs run schedule-hippique-09h --location=$REGION

echo -e "\n=== Vérifier les logs dans 30 secondes ==="
sleep 30
gcloud scheduler jobs describe schedule-hippique-09h --location=$REGION
