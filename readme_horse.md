# 🐴 Orchestrateur Hippique Cloud Run - GPI v5.1

Système d'orchestration automatisé pour l'analyse pronostique hippique, déployé sur Google Cloud Run avec planification via Cloud Tasks et Cloud Scheduler.

## 📋 Table des matières

- [Architecture](#architecture)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Configuration](#configuration)
- [Déploiement](#déploiement)
- [Utilisation](#utilisation)
- [Monitoring](#monitoring)
- [Dépannage](#dépannage)

---

## 🏗️ Architecture

### Composants

```
┌─────────────────────────────────────────────────────────────┐
│                     Cloud Scheduler                         │
│                   (Quotidien 09:00 CET)                     │
└────────────────────────┬────────────────────────────────────┘
                         │ POST /schedule
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Cloud Run Service                         │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  FastAPI Endpoints                                   │  │
│  │  - POST /schedule → Génère plan + programme tasks   │  │
│  │  - POST /run → Exécute analyse GPI v5.1            │  │
│  │  - GET /healthz → Health check                      │  │
│  └─────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │ Crée tasks H-30 & H-5
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     Cloud Tasks Queue                       │
│  (Planification précise des exécutions par course)         │
└────────────────────────┬────────────────────────────────────┘
                         │ POST /run (H-30, H-5)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Modules GPI v5.1                          │
│  - analyse_courses_du_jour_enrichie.py                     │
│  - p_finale_export.py                                       │
│  - simulate_ev.py                                           │
│  - pipeline_run.py                                          │
│  - update_excel_with_results.py (post-course)              │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
                  ┌─────────────┐
                  │  GCS Bucket │ (Optionnel)
                  │  Artefacts  │
                  └─────────────┘
```

### Flux d'exécution

1. **09:00 Europe/Paris** : Cloud Scheduler déclenche `POST /schedule`
2. **Génération du plan** : Parsing ZEturf + Geny → `plan.json` (toutes les courses du jour)
3. **Programmation** : Pour chaque course, création de 2 Cloud Tasks :
   - **H-30** : 30 minutes avant la course
   - **H-5** : 5 minutes avant la course
4. **Exécution** : Cloud Tasks invoque `POST /run` aux heures précises
5. **Analyse GPI** : Modules Python exécutés en séquence
6. **Archivage** : Upload des artefacts sur GCS (optionnel)

---

## ✅ Prérequis

### Outils requis

- **gcloud CLI** (authentifié) : `gcloud auth login`
- **Docker** : Pour le build local (optionnel)
- **Python 3.11+** : Pour tests locaux

### APIs GCP à activer

```bash
gcloud services enable \
  run.googleapis.com \
  cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com \
  --project=YOUR_PROJECT_ID
```

### Permissions IAM

Le Service Account utilisé doit avoir :
- `roles/run.invoker` (invoquer Cloud Run)
- `roles/cloudtasks.enqueuer` (créer des tasks)
- `roles/storage.objectAdmin` (si GCS utilisé)

---

## 📦 Installation

### 1. Cloner ou créer l'arborescence

```bash
mkdir horse-racing-orchestrator
cd horse-racing-orchestrator

# Créer l'arborescence
mkdir -p src scripts gpi_modules
```

### 2. Copier les fichiers

Placez les fichiers suivants :

```
/
├── src/
│   ├── service.py
│   ├── plan.py
│   ├── scheduler.py
│   ├── runner.py
│   ├── config.py
│   ├── logging_utils.py
│   └── time_utils.py
├── gpi_modules/
│   ├── analyse_courses_du_jour_enrichie.py
│   ├── p_finale_export.py
│   ├── simulate_ev.py
│   ├── pipeline_run.py
│   └── ... (autres modules GPI)
├── scripts/
│   ├── deploy_cloud_run.sh
│   └── create_scheduler_0900.sh
├── Dockerfile
├── gunicorn.conf.py
├── requirements.txt
├── .env.example
└── README.md
```

### 3. Configuration

```bash
# Copier le template
cp .env.example .env

# Éditer avec vos valeurs
nano .env
```

**Variables critiques à remplir** :
```bash
PROJECT_ID=votre-project-id
REGION=europe-west1
SCHEDULER_SA_EMAIL=votre-sa@project.iam.gserviceaccount.com
GCS_BUCKET=votre-bucket  # Optionnel
```

---

## 🚀 Déploiement

### Déploiement automatisé (recommandé)

```bash
# Rendre les scripts exécutables
chmod +x scripts/*.sh

# 1. Déployer Cloud Run
./scripts/deploy_cloud_run.sh

# 2. Créer le job quotidien 09:00
./scripts/create_scheduler_0900.sh
```

Le script `deploy_cloud_run.sh` effectue :
- ✅ Création du Service Account
- ✅ Build de l'image Docker via Cloud Build
- ✅ Déploiement sur Cloud Run
- ✅ Configuration IAM
- ✅ Création de la queue Cloud Tasks
- ✅ Test du healthcheck

### Déploiement manuel

```bash
# 1. Build image
gcloud builds submit --tag gcr.io/PROJECT_ID/horse-racing-orchestrator

# 2. Deploy
gcloud run deploy horse-racing-orchestrator \
  --image gcr.io/PROJECT_ID/horse-racing-orchestrator \
  --platform managed \
  --region europe-west1 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --no-allow-unauthenticated \
  --service-account SA_EMAIL

# 3. Récupérer l'URL
SERVICE_URL=$(gcloud run services describe horse-racing-orchestrator \
  --region europe-west1 --format 'value(status.url)')

# 4. Créer la queue
gcloud tasks queues create horse-racing-queue \
  --location=europe-west1

# 5. Créer le scheduler
gcloud scheduler jobs create http daily-plan-0900 \
  --location=europe-west1 \
  --schedule="0 9 * * *" \
  --time-zone="Europe/Paris" \
  --uri="${SERVICE_URL}/schedule" \
  --http-method=POST \
  --message-body='{"date":"today","mode":"tasks"}' \
  --oidc-service-account-email=SA_EMAIL \
  --oidc-token-audience=${SERVICE_URL}
```

---

## 🎮 Utilisation

### Test manuel du planning

```bash
# Obtenir un token d'authentification
TOKEN=$(gcloud auth print-identity-token --audiences=$SERVICE_URL)

# Déclencher le planning pour aujourd'hui
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"date":"today","mode":"tasks"}' \
  $SERVICE_URL/schedule
```

**Réponse attendue** :
```json
{
  "ok": true,
  "correlation_id": "uuid-xxx",
  "plan_path": "/tmp/horse_data/plan.json",
  "races_count": 42,
  "tasks_scheduled": 42,
  "tasks": [
    {
      "race": "R1C1",
      "meeting": "VINCENNES",
      "time_local": "14:15",
      "h30_task": "projects/.../tasks/run-20251016-r1c1-h30",
      "h30_time_utc": "2025-10-16 11:45:00 UTC",
      "h5_task": "projects/.../tasks/run-20251016-r1c1-h5",
      "h5_time_utc": "2025-10-16 12:10:00 UTC"
    }
  ]
}
```

### Test d'une exécution de course

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "course_url": "https://www.zeturf.fr/fr/course/2025-10-16/R1C3-vincennes",
    "phase": "H30",
    "date": "2025-10-16"
  }' \
  $SERVICE_URL/run
```

### Vérification santé

```bash
curl -H "Authorization: Bearer $TOKEN" $SERVICE_URL/healthz
```

---

## 📊 Monitoring

### Logs Cloud Run

```bash
# Tous les logs
gcloud logging read "resource.type=cloud_run_revision" \
  --limit 100 \
  --format json

# Logs avec corrélation (tracer une course)
gcloud logging read \
  "resource.type=cloud_run_revision AND jsonPayload.correlation_id=\"xxx\"" \
  --format json

# Erreurs uniquement
gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR" \
  --limit 50
```

### Logs Scheduler

```bash
gcloud logging read "resource.type=cloud_scheduler_job" \
  --limit 10
```

### Cloud Tasks

```bash
# Lister les tâches en attente
gcloud tasks list --queue=horse-racing-queue --location=europe-west1

# Voir une tâche spécifique
gcloud tasks describe TASK_NAME \
  --queue=horse-racing-queue \
  --location=europe-west1
```

### Métriques Cloud Run

```bash
# Dans la console GCP
https://console.cloud.google.com/run/detail/REGION/SERVICE_NAME/metrics
```

Métriques clés :
- **Request count** : Nombre d'invocations
- **Request latency** : Temps de réponse
- **Container instances** : Scaling
- **Memory utilization** : RAM utilisée

---

## 🔧 Dépannage

### Problème : "Permission denied" sur Cloud Run

**Solution** :
```bash
# Vérifier IAM
gcloud run services get-iam-policy SERVICE_NAME --region=REGION

# Ajouter le SA comme invoker
gcloud run services add-iam-policy-binding SERVICE_NAME \
  --region=REGION \
  --member="serviceAccount:SA_EMAIL" \
  --role="roles/run.invoker"
```

### Problème : Tâches non exécutées

**Diagnostic** :
```bash
# Lister les tâches
gcloud tasks list --queue=horse-racing-queue --location=europe-west1

# Logs de la queue
gcloud logging read "resource.type=cloud_tasks_queue"
```

**Solutions** :
- Vérifier que la queue existe
- Vérifier le SA a `roles/run.invoker`
- Vérifier l'URL du service dans les tâches

### Problème : Parsing échoue (ZEturf/Geny)

**Diagnostic** :
```bash
# Voir les logs d'erreur de parsing
gcloud logging read \
  "resource.type=cloud_run_revision AND textPayload=~\"Error parsing\"" \
  --limit 20
```

**Solutions** :
- Vérifier la structure HTML (peut changer)
- Ajuster les sélecteurs CSS dans `src/plan.py`
- Augmenter `RATE_LIMIT_DELAY` si 429/throttle

### Problème : Module GPI manquant

**Diagnostic** :
```bash
# Voir stderr des exécutions
gcloud logging read \
  "resource.type=cloud_run_revision AND jsonPayload.stderr_tail=~\"Script not found\""
```

**Solutions** :
- Vérifier que `gpi_modules/` est copié dans l'image
- Ajuster `self.gpi_base` dans `src/runner.py`
- Rebuild l'image

---

## 🔐 Sécurité

### Bonnes pratiques

1. **Service Account dédié** : Ne jamais utiliser le SA par défaut
2. **Principe du moindre privilège** : Accorder uniquement les rôles nécessaires
3. **Pas de secrets dans le code** : Utiliser Secret Manager
4. **Cloud Run privé** : `--no-allow-unauthenticated`
5. **OIDC activé** : Authentification par token

### Secrets (optionnel)

```bash
# Créer un secret
echo -n "valeur-secrete" | gcloud secrets create SECRET_NAME \
  --data-file=- \
  --replication-policy=automatic

# Monter dans Cloud Run
gcloud run services update SERVICE_NAME \
  --update-secrets=ENV_VAR=SECRET_NAME:latest
```

---

## 🧪 Tests locaux

### Avec Docker

```bash
# Build
docker build -t horse-racing-orchestrator .

# Run
docker run -p 8080:8080 \
  -e PROJECT_ID=test \
  -e REQUIRE_AUTH=false \
  horse-racing-orchestrator
```

### Sans Docker

```bash
# Installer dépendances
pip install -r requirements.txt

# Lancer
export REQUIRE_AUTH=false
uvicorn src.service:app --reload --port 8080
```

---

## 📚 Ressources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Cloud Tasks](https://cloud.google.com/tasks/docs)
- [Cloud Scheduler](https://cloud.google.com/scheduler/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

---

## 📝 Changelog

### v1.0.0 (2025-10-16)
- ✅ Déploiement initial Cloud Run
- ✅ Orchestration Cloud Tasks
- ✅ Scheduler quotidien 09:00
- ✅ Intégration GPI v5.1
- ✅ Logging structuré
- ✅ Support GCS

---

## 📄 Licence

Usage éducatif uniquement. Respecter les CGU des sites sources (ZEturf, Geny).

---

## 🤝 Support

Pour toute question :
1. Consulter les logs : `gcloud logging read ...`
2. Vérifier le healthcheck
3. Tester manuellement les endpoints

**Happy racing! 🐴**
