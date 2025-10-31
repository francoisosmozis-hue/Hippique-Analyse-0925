#!/bin/bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-analyse-hippique}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-hippique-orchestrator}"
QUEUE_ID="${QUEUE_ID:-hippique-tasks}"

SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region=${REGION} --format='value(status.url)' 2>/dev/null || echo "")

[[ -z "${SERVICE_URL}" ]] && echo "❌ Service non trouvé" && exit 1

echo "=== Test Schedule ==="
echo "📍 URL: ${SERVICE_URL}"
echo ""

RESPONSE=$(curl -sf -X POST "${SERVICE_URL}/schedule" \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d '{"date":"today","mode":"tasks"}' || echo '{"error":"failed"}')

echo "${RESPONSE}" | jq . 2>/dev/null || echo "${RESPONSE}"
echo ""

OK=$(echo "${RESPONSE}" | jq -r '.ok // false')
TOTAL=$(echo "${RESPONSE}" | jq -r '.total_races // 0')
H30=$(echo "${RESPONSE}" | jq -r '.scheduled_h30 // 0')
H5=$(echo "${RESPONSE}" | jq -r '.scheduled_h5 // 0')
ERROR=$(echo "${RESPONSE}" | jq -r '.error // ""')

echo "=== Résumé ==="
echo "✅ OK: ${OK}"
echo "📅 Date: $(echo "${RESPONSE}" | jq -r '.date // "unknown"')"
echo "📊 Courses: ${TOTAL}"
echo "🎯 Tâches créées: H-30=${H30}, H-5=${H5}"
[[ -n "${ERROR}" ]] && echo "❌ Erreur: ${ERROR}"

echo ""
echo "=== Tâches Cloud Tasks ==="
TASK_COUNT=$(gcloud tasks list --queue="${QUEUE_ID}" --location="${REGION}" --format="value(name)" 2>/dev/null | wc -l || echo "0")
echo "Tâches en attente: ${TASK_COUNT}"

[[ "${TASK_COUNT}" -eq 0 ]] && echo "⚠️  Aucune tâche créée - vérifier les logs"

[[ "${OK}" == "true" ]] && [[ "${TASK_COUNT}" -gt 0 ]] && echo "✅ SUCCESS" || echo "⚠️  Vérifier les logs"
