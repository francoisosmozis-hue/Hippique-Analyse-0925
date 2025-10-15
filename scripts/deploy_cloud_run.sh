# Déploiement Cloud Run - Analyse Hippique GPI v5.1

## Architecture

```
Cloud Scheduler (09:00 Paris)
    ↓
Cloud Run Service (POST /schedule)
    ↓
Cloud Tasks Queue
    ↓ (H-30 et H-5 pour chaque course)
Cloud Run Service (POST /run)
    ↓
Runner Chain → GCS Upload
```

## Prérequis

1. **Projet GCP** avec APIs activées:
   ```bash
   gcloud services enable \
     run.googleapis.com \
     cloudtasks.googleapis.com \
     cloudscheduler.googleapis.com \
     cloudbuild.googleapis.com \
     storage.googleapis.com
   ```

2. **Service Account** avec roles:
   - `roles/run.invoker` (pour Cloud Scheduler → Cloud Run)
   - `roles/cloudtasks.enqueuer` (pour créer des tâches)
   - `roles/storage.objectAdmin` (pour GCS)

3. **Cloud Tasks Queue**:
   ```bash
   gcloud tasks queues create hippique-tasks --location=europe-west1
   ```

4. **GCS Bucket**:
   ```bash
   gsutil mb -p YOUR_PROJECT -l europe-west1 gs://your-hippique-bucket
   ```

## Déploiement

### 1. Configuration

Copier `.env.example` et ajuster:
```bash
cp .env.example .env
# Éditer .env avec vos valeurs
```

### 2. Build & Deploy

```bash
export PROJECT_ID=your-project-id
export SA_EMAIL=hippique-sa@your-project-id.iam.gserviceaccount.com
export GCS_BUCKET=your-hippique-bucket

./scripts/deploy_cloud_run.sh
```

### 3. Créer le Scheduler quotidien

```bash
./scripts/create_scheduler_0900.sh
```

## Endpoints

### GET /healthz
Health check
```bash
curl https://your-service-url.run.app/healthz
```

### POST /schedule
Génère le plan et programme H-30/H-5
```bash
curl -X POST https://your-service-url.run.app/schedule \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"date":"2025-01-15","mode":"tasks"}'
```

Réponse:
```json
{
  "ok": true,
  "date": "2025-01-15",
  "races_count": 42,
  "scheduled_count": 42,
  "scheduled_tasks": [
    {
      "race_id": "R1C1",
      "race_time": "13:45",
      "h30_scheduled": "2025-01-15T13:15:00+01:00",
      "h5_scheduled": "2025-01-15T13:40:00+01:00",
      "tasks": [...]
    }
  ]
}
```

### POST /run
Exécute l'analyse d'une course
```bash
curl -X POST https://your-service-url.run.app/run \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "course_url":"https://www.zeturf.fr/fr/course/2025-01-15/R1C1-paris-vincennes",
    "phase":"H30",
    "date":"2025-01-15"
  }'
```

Réponse:
```json
{
  "ok": true,
  "rc": 0,
  "race_id": "R1C1",
  "phase": "H30",
  "artifacts": {
    "snapshot_H30.json": "/tmp/data/R1C1/snapshot_H30.json",
    "h30.json": "/tmp/data/R1C1/h30.json"
  }
}
```

## Workflow quotidien

1. **09:00 Paris**: Cloud Scheduler → `POST /schedule`
   - Construit le plan via ZEturf + Geny
   - Crée ~80 tâches Cloud Tasks (H-30 + H-5 pour chaque course)

2. **H-30**: Cloud Tasks → `POST /run` avec `phase=H30`
   - Snapshot cotes
   - Stats J/E si disponibles
   - Upload GCS

3. **H-5**: Cloud Tasks → `POST /run` avec `phase=H5`
   - Enrichissement chronos
   - Pipeline GPI (tickets, EV/ROI)
   - Export JSON/CSV/Excel
   - Upload GCS

## Monitoring

### Logs
```bash
# Service logs
gcloud logs read "resource.type=cloud_run_revision AND resource.labels.service_name=hippique-orchestrator" \
  --project=YOUR_PROJECT --limit=50 --format=json

# Scheduler logs
gcloud scheduler jobs logs read hippique-daily-planning \
  --location=europe-west1 --limit=50

# Tasks logs
gcloud tasks queues describe hippique-tasks --location=europe-west1
```

### Métriques
Dans Cloud Console:
- Cloud Run > hippique-orchestrator > Metrics
- Cloud Tasks > hippique-tasks > Metrics

## Troubleshooting

### Erreur "No races found"
- Vérifier que `scripts/fetch_reunions_geny.py` fonctionne
- Vérifier que `scripts/online_fetch_zeturf.py --mode planning` retourne des données

### Timeout sur /run
- Augmenter `--timeout` lors du deploy (max 3600s)
- Vérifier les logs du runner_chain.py

### Tasks non exécutées
- Vérifier IAM: service account doit avoir `roles/run.invoker`
- Vérifier que la queue n'est pas en pause

### Upload GCS échoue
- Vérifier `GCS_BUCKET` et `GCS_PREFIX`
- Vérifier IAM: service account doit avoir `roles/storage.objectAdmin`

## Coûts estimés

- Cloud Run: ~10€/mois (2Gi RAM, peu de trafic)
- Cloud Tasks: ~0€ (< 1M tâches/mois gratuit)
- Cloud Scheduler: ~0.10€/mois (1 job)
- GCS: ~1€/mois (stockage + operations)

**Total: ~11€/mois**

## Sécurité

✅ Service privé avec OIDC  
✅ Service account dédié avec principe du moindre privilège  
✅ Secrets via Secret Manager (si credentials.json nécessaire)  
✅ Logs structurés JSON vers Cloud Logging  
✅ Pas de stockage localStorage (non supporté)

## Support

Pour questions/bugs, ouvrir une issue sur le repo.
