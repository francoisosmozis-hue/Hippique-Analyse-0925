# Déploiement Cloud Run Jobs

Cette procédure exploite Workload Identity Federation (OIDC) pour publier le
conteneur et déclencher un **Cloud Run Job** planifié via **Cloud Scheduler**.
Aucune clé JSON de compte de service n’est utilisée.

## Pré-requis

- Un projet GCP avec les API suivantes activées :
  - `run.googleapis.com`
  - `cloudbuild.googleapis.com`
  - `cloudscheduler.googleapis.com`
  - `artifactregistry.googleapis.com`
- Un Workload Identity Pool et un provider OIDC relié au dépôt GitHub.
- Un compte de service avec les rôles :
  - `roles/run.admin`
  - `roles/artifactregistry.admin`
  - `roles/cloudscheduler.admin`
  - `roles/iam.serviceAccountTokenCreator`
- Variables GitHub Actions renseignées :
  - `GCP_PROJECT_ID`, `GCP_REGION`
  - `GCP_WIF_PROVIDER`, `GCP_SERVICE_ACCOUNT`
  - `CLOUD_RUN_JOB_NAME`, `CLOUD_RUN_SCHEDULER_NAME`, `CLOUD_RUN_SCHEDULE`
  - `ARTIFACT_REPO` (nom du dépôt Artifact Registry)

## Pipeline de déploiement

Le workflow [`deploy-cloudrun.yml`](../.github/workflows/deploy-cloudrun.yml)
réalise les étapes suivantes :

1. Authentification via WIF.
2. Construction de l’image et push dans Artifact Registry :
   ```bash
   gcloud builds submit --tag $REGION-docker.pkg.dev/$PROJECT/$REPO/hippique-analyse:$TAG .
   ```
3. Publication du Cloud Run Job :
   ```bash
   gcloud run jobs deploy $JOB_NAME \
     --image $IMAGE_URI \
     --region $REGION \
     --max-retries 1 \
     --set-env-vars PIPELINE_MODE=hminus5,OUTPUT_DIR=/app/out
   ```
4. Création/mise à jour du Cloud Scheduler :
   ```bash
   gcloud scheduler jobs update http $SCHEDULER_NAME \
     --location $REGION \
     --schedule "$CRON" \
     --uri "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/$JOB_NAME:run" \
     --http-method POST \
     --oidc-service-account-email $SERVICE_ACCOUNT
   ```

## Vérifications post-déploiement

Afficher l’état du job et du scheduler :

```bash
gcloud run jobs list --region $REGION --project $PROJECT
gcloud scheduler jobs list --location $REGION --project $PROJECT
```

Exécuter manuellement le job si nécessaire :

```bash
gcloud run jobs execute $JOB_NAME --region $REGION --project $PROJECT
```
