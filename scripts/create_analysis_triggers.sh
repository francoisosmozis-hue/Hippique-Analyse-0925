#!/bin/bash
set -e

# ============================================================================
# Crée les Cloud Schedulers pour les déclenchements H-30 et H-5.
# Ces schedulers publient un message dans un topic Pub/Sub à intervalle régulier.
# ============================================================================

# --- Configuration ---
PROJECT_ID=${PROJECT_ID:-$(gcloud config get-value project)}
REGION=${REGION:-"europe-west1"}
TOPIC_NAME="run-analysis-triggers"
CRON_SCHEDULE="*/2 * * * *" # Toutes les 2 minutes

# Noms des jobs
JOB_H30="trigger-h30-analysis"
JOB_H5="trigger-h5-analysis"

# Messages à publier
MESSAGE_H30='{"phase": "H30"}'
MESSAGE_H5='{"phase": "H5"}'

echo "Configuration des triggers d'analyse pour le projet ${PROJECT_ID}..."

# --- Fonction pour créer/mettre à jour un job ---
create_or_update_pubsub_job() {
    local job_name=$1
    local message_body=$2
    local schedule=$3
    local topic=$4

    echo ""
    echo "--- Configuration du job: ${job_name} ---"

    if gcloud scheduler jobs describe "${job_name}" --location="${REGION}" >/dev/null 2>&1; then
        echo "Le job '${job_name}' existe déjà. Mise à jour..."
        gcloud scheduler jobs update pubsub "${job_name}" \
            --location="${REGION}" \
            --schedule="${schedule}" \
            --topic="${topic}" \
            --message-body="${message_body}"
    else
        echo "Création du job '${job_name}'..."
        gcloud scheduler jobs create pubsub "${job_name}" \
            --location="${REGION}" \
            --schedule="${schedule}" \
            --topic="${topic}" \
            --message-body="${message_body}" \
            --time-zone="Europe/Paris"
    fi
    echo "Job '${job_name}' configuré avec succès."
}

# --- Création des jobs ---
create_or_update_pubsub_job "${JOB_H30}" "${MESSAGE_H30}" "${CRON_SCHEDULE}" "${TOPIC_NAME}"
create_or_update_pubsub_job "${JOB_H5}" "${MESSAGE_H5}" "${CRON_SCHEDULE}" "${TOPIC_NAME}"

echo ""

echo "✅ Terminé."
echo "Les schedulers '${JOB_H30}' et '${JOB_H5}' vont maintenant déclencher les analyses toutes les 2 minutes."
