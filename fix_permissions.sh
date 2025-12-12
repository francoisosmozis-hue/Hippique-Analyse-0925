#!/bin/bash

# ==============================================================================
# Script de Correction des Permissions IAM pour le Service Hippique Orchestrator
#
# Ce script applique le principe de moindre privilège au compte de service
# de l'application en retirant les rôles larges (editor) et en ajoutant
# uniquement les permissions granulaires nécessaires.
#
# USAGE:
#   1. Assurez-vous d'être authentifié avec gcloud : `gcloud auth login`
#   2. Assurez-vous d'avoir sélectionné le bon projet : `gcloud config set project analyse-hippique`
#   3. Rendez le script exécutable : `chmod +x fix_permissions.sh`
#   4. Exécutez le script : `./fix_permissions.sh`
# ==============================================================================

# Arrête le script en cas d'erreur
set -e
# Affiche chaque commande avant de l'exécuter
set -x

# --- Configuration ---
PROJECT_ID="analyse-hippique"
SERVICE_ACCOUNT="hippique-orchestrator@${PROJECT_ID}.iam.gserviceaccount.com"
MEMBER="serviceAccount:${SERVICE_ACCOUNT}"

# --- Rôles à retirer (trop permissifs) ---
echo "--- Retrait des rôles larges et dangereux ---"
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/editor" --condition=None --quiet || echo "Le rôle roles/editor n'était pas présent ou a déjà été retiré."
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/assuredoss.admin" --condition=None --quiet || echo "Le rôle roles/assuredoss.admin n'était pas présent ou a déjà été retiré."
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/deploymentmanager.editor" --condition=None --quiet || echo "Le rôle roles/deploymentmanager.editor n'était pas présent ou a déjà été retiré."
gcloud projects remove-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/iam.infrastructureAdmin" --condition=None --quiet || echo "Le rôle roles/iam.infrastructureAdmin n'était pas présent ou a déjà été retiré."

# --- Rôles à ajouter (spécifiques et nécessaires) ---
echo "--- Ajout des rôles granulaires requis ---"
# Permission de lire/écrire dans Firestore
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/datastore.user" --quiet
# Permission de gérer les objets dans Google Cloud Storage
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/storage.objectAdmin" --quiet
# Permission de créer des tâches dans Cloud Tasks
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/cloudtasks.enqueuer" --quiet
# Permission d'être invoqué par Cloud Run, Cloud Tasks, et d'autres services
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/run.invoker" --quiet
# Permission d'écrire des logs
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/logging.logWriter" --quiet
# Permission d'accéder aux secrets (si utilisé)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="${MEMBER}" --role="roles/secretmanager.secretAccessor" --quiet

set +x
echo ""
echo "✅ Permissions corrigées avec succès pour le compte de service ${SERVICE_ACCOUNT}"
echo "Vérification des nouveaux rôles :"
gcloud projects get-iam-policy ${PROJECT_ID} \
    --flatten="bindings[].members" \
    --filter="bindings.members:${MEMBER}" \
    --format="table(bindings.role)"
