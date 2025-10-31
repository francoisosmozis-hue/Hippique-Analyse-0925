# 📁 Structure du projet - Orchestrateur Hippique Cloud Run

Vue d'ensemble complète du dépôt avec descriptions de tous les fichiers.

---

## 🗂️ Arborescence complète

```
horse-racing-orchestrator/
│
├── src/                              # Code source principal
│   ├── service.py                    # API FastAPI (3 endpoints)
│   ├── plan.py                       # Construction du plan quotidien
│   ├── scheduler.py                  # Cloud Tasks + Scheduler
│   ├── runner.py                     # Orchestration modules GPI
│   ├── config.py                     # Configuration centralisée
│   ├── logging_utils.py              # Logging JSON structuré
│   └── time_utils.py                 # Gestion timezone Paris<->UTC
│
├── gpi_modules/                      # Modules d'analyse GPI v5.1
│   ├── analyse_courses_du_jour_enrichie.py
│   ├── online_fetch_zeturf.py
│   ├── fetch_je_stats.py
│   ├── fetch_je_chrono.py
│   ├── p_finale_export.py
│   ├── simulate_ev.py
│   ├── pipeline_run.py
│   ├── update_excel_with_results.py
│   └── get_arrivee_geny.py
│
├── scripts/                          # Scripts d'automatisation
│   ├── deploy_cloud_run.sh          # Déploiement automatisé
│   ├── create_scheduler_0900.sh     # Configuration scheduler
│   ├── test_local.sh                # Tests locaux
│   ├── monitor.sh                   # Monitoring en temps réel
│   └── generate_test_plan.py        # Générateur de données test
│
├── tests/                            # Suite de tests
│   ├── conftest.py                  # Fixtures pytest
│   ├── test_time_utils.py           # Tests timezone
│   ├── test_plan.py                 # Tests plan builder
│   ├── test_scheduler.py            # Tests Cloud Tasks
│   ├── test_runner.py               # Tests GPI runner
│   ├── test_service.py              # Tests API FastAPI
│   ├── test_integration.py          # Tests d'intégration
│   └── test_edge_cases.py           # Tests cas limites
│
├── Dockerfile                        # Image Docker production
├── gunicorn.conf.py                  # Configuration Gunicorn
├── requirements.txt                  # Dépendances Python
├── pytest.ini                        # Configuration pytest
│
├── .env.example                      # Template configuration
├── .gitignore                        # Exclusions Git
├── .dockerignore                     # Exclusions Docker
│
├── Makefile                          # Commandes simplifiées
│
├── README.md                         # Documentation principale
├── QUICKSTART.md                     # Guide démarrage rapide
├── TROUBLESHOOTING.md                # Guide dépannage
└── PROJECT_STRUCTURE.md              # Ce fichier
```

---

## 📄 Description des fichiers clés

### **src/service.py** (API FastAPI)
```python
# 3 endpoints principaux:
POST /schedule    # Génère plan + programme H-30/H-5
POST /run         # Exécute analyse d'une course
GET  /healthz     # Health check

# Features:
- Authentification OIDC optionnelle
- Logging structuré JSON
- Gestion d'erreurs explicite
- Correlation IDs pour traçabilité
```

### **src/plan.py** (Plan Builder)
```python
# Responsabilités:
- Parser programme ZEturf (source principale)
- Fallback Geny pour heures manquantes
- Déduplication par (date, R, C)
- Tri chronologique
- Validation structure

# Méthodes principales:
build_plan(date) -> list[dict]
_parse_zeturf_program(date) -> list[dict]
_fill_times_from_geny(date, plan) -> None
_deduplicate_and_sort(plan) -> list[dict]
```

### **src/scheduler.py** (Cloud Tasks)
```python
# Responsabilités:
- Créer tâches Cloud Tasks avec scheduleTime précis
- Noms déterministes pour idempotence
- Conversion timezone Europe/Paris -> UTC
- Fallback Cloud Scheduler (optionnel)

# Méthodes principales:
enqueue_run_task(...) -> str  # Retourne task name
```

### **src/runner.py** (GPI Orchestrator)
```python
# Responsabilités:
- Exécuter séquentiellement les modules GPI
- Capturer stdout/stderr
- Gérer timeouts
- Collecter artefacts (JSON, CSV, Excel)
- Upload GCS optionnel

# Pipeline:
1. analyse_courses_du_jour_enrichie.py
2. p_finale_export.py
3. simulate_ev.py
4. pipeline_run.py
5. (post-course) update_excel_with_results.py
```

### **src/config.py** (Configuration)
```python
# Variables d'environnement gérées:
- GCP: PROJECT_ID, REGION, SERVICE_URL
- Auth: REQUIRE_AUTH, OIDC_AUDIENCE
- Storage: GCS_BUCKET, LOCAL_DATA_DIR
- Throttling: RATE_LIMIT_DELAY, REQUEST_TIMEOUT
- GPI: BUDGET_PER_RACE, MIN_EV_PERCENT

# Validation avec Pydantic
```

### **src/logging_utils.py** (Logging)
```python
# Format JSON structuré pour Cloud Logging
{
  "timestamp": "2025-10-16T14:30:00Z",
  "severity": "INFO",
  "message": "...",
  "correlation_id": "uuid-xxx",
  "exception": [...]  # Si erreur
}
```

### **src/time_utils.py** (Timezone)
```python
# Fonctions principales:
now_paris() -> datetime
parse_local_time(date, time) -> datetime
to_utc(dt_paris) -> datetime
to_paris(dt_utc) -> datetime
to_rfc3339(dt) -> str
calculate_snapshots(race_time) -> (h30, h5)

# Gestion DST automatique (zoneinfo)
```

---

## 🚀 Scripts d'automatisation

### **scripts/deploy_cloud_run.sh**
```bash
# Actions:
1. Créer Service Account si nécessaire
2. Build image via Cloud Build
3. Deploy sur Cloud Run
4. Configurer IAM (roles/run.invoker)
5. Créer queue Cloud Tasks
6. Test healthcheck

# Usage:
./scripts/deploy_cloud_run.sh
./scripts/deploy_cloud_run.sh --no-build  # Skip build
```

### **scripts/create_scheduler_0900.sh**
```bash
# Actions:
1. Créer job "daily-plan-0900"
2. Schedule: 0 9 * * * (Europe/Paris)
3. Target: POST /schedule
4. Auth: OIDC avec SA

# Usage:
./scripts/create_scheduler_0900.sh
```

### **scripts/test_local.sh**
```bash
# Tests:
1. Healthcheck
2. POST /schedule
3. POST /run (simulation)
4. Logs structurés

# Usage:
./scripts/test_local.sh --no-auth        # Local
SERVICE_URL=https://... ./test_local.sh  # Prod
```

### **scripts/monitor.sh**
```bash
# Affichage:
- État service Cloud Run
- Queue Cloud Tasks (nombre tâches)
- Jobs Scheduler
- Métriques 24h (requêtes, erreurs)
- Alertes & anomalies
- Derniers logs

# Usage:
./scripts/monitor.sh                  # One-shot
./scripts/monitor.sh --watch 30       # Refresh 30s
./scripts/monitor.sh --alerts         # Alertes uniquement
```

### **scripts/generate_test_plan.py**
```bash
# Génère un plan.json fictif pour tests
python scripts/generate_test_plan.py \
  --date 2025-10-16 \
  --races 10 \
  --output plan_test.json
```

---

## 🧪 Tests

### **Structure des tests**
```
tests/
├── conftest.py              # Fixtures communes
├── test_time_utils.py       # 6 tests timezone
├── test_plan.py             # 5 tests plan builder
├── test_scheduler.py        # 4 tests Cloud Tasks
├── test_runner.py           # 7 tests GPI runner
├── test_service.py          # 5 tests API FastAPI
├── test_integration.py      # 2 tests intégration
└── test_edge_cases.py       # 3 tests cas limites
```

### **Markers pytest**
```python
@pytest.mark.unit              # Tests unitaires
@pytest.mark.integration       # Tests intégration
@pytest.mark.slow              # Tests >1s
@pytest.mark.requires_gcp      # Tests nécessitant GCP
```

### **Exécution**
```bash
# Tous les tests
pytest

# Tests unitaires uniquement
pytest -m unit

# Avec couverture
pytest --cov=src --cov-report=html

# Tests spécifiques
pytest tests/test_plan.py::test_deduplicate_and_sort
```

---

## 🐳 Docker

### **Dockerfile**
```dockerfile
FROM python:3.11-slim

# Dépendances système: lxml, tzdata
# Install requirements.txt
# COPY src/ et gpi_modules/
# ENV PORT=8080, PYTHONUNBUFFERED=1
# CMD: gunicorn avec uvicorn workers

# Build:
docker build -t horse-racing-orchestrator .

# Run local:
docker run -p 8080:8080 \
  -e REQUIRE_AUTH=false \
  horse-racing-orchestrator
```

### **gunicorn.conf.py**
```python
bind = "0.0.0.0:8080"
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 300
preload_app = False
max_requests = 1000
```

---

## 📋 Makefile (commandes pratiques)

```makefile
make help          # Afficher aide
make setup         # Setup initial (APIs, SA)
make build         # Build image localement
make run-local     # Lancer en local
make deploy        # Déployer sur Cloud Run
make deploy-fast   # Deploy sans rebuild
make scheduler     # Créer job 09:00
make test-local    # Tests locaux
make test-prod     # Tests production
make logs          # Logs Cloud Run
make logs-errors   # Erreurs uniquement
make tasks-list    # Tâches en attente
make trigger-schedule  # Déclencher planning manuellement
make status        # Statut complet
make clean         # Nettoyer tâches
make destroy       # Supprimer TOUT
```

---

## 🔧 Configuration (.env)

### **Variables critiques**
```bash
# GCP
PROJECT_ID=your-project
REGION=europe-west1
SERVICE_NAME=horse-racing-orchestrator
SERVICE_URL=https://...cloudrun.app
QUEUE_ID=horse-racing-queue

# Service Account
SCHEDULER_SA_EMAIL=sa@project.iam.gserviceaccount.com

# Auth
REQUIRE_AUTH=true
OIDC_AUDIENCE=${SERVICE_URL}

# Storage
GCS_BUCKET=your-bucket  # Optionnel
LOCAL_DATA_DIR=/tmp/horse_data

# Throttling
RATE_LIMIT_DELAY=1.0
REQUEST_TIMEOUT=30
MAX_RETRIES=3

# GPI
GPI_BUDGET_PER_RACE=5.0
GPI_MIN_EV_PERCENT=40.0
```

---

## 📦 Dépendances (requirements.txt)

### **Web Framework**
- fastapi==0.104.1
- uvicorn[standard]==0.24.0
- gunicorn==21.2.0

### **GCP**
- google-cloud-tasks==2.14.2
- google-cloud-scheduler==2.11.3
- google-cloud-storage==2.10.0
- google-auth==2.23.4

### **HTTP & Parsing**
- requests==2.31.0
- httpx==0.25.1
- beautifulsoup4==4.12.2
- lxml==4.9.3

### **Data**
- pandas==2.1.3
- numpy==1.26.2
- openpyxl==3.1.2

### **Utils**
- python-json-logger==2.0.7
- python-dateutil==2.8.2
- tenacity==8.2.3

---

## 🔄 Workflow typique

### **Développement local**
```bash
# 1. Setup
cp .env.example .env
nano .env  # Configurer

# 2. Installer dépendances
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Tests
pytest -m unit

# 4. Lancer localement
export REQUIRE_AUTH=false
uvicorn src.service:app --reload --port 8080

# 5. Tester
./scripts/test_local.sh --no-auth
```

### **Déploiement production**
```bash
# 1. Setup GCP
make setup

# 2. Déployer
make deploy

# 3. Configurer scheduler
make scheduler

# 4. Tester
make test-prod

# 5. Monitorer
make status
make logs
./scripts/monitor.sh --watch 30
```

### **Opérations courantes**
```bash
# Voir les tâches
make tasks-list

# Déclencher planning manuellement
make trigger-schedule

# Voir les erreurs
make logs-errors

# Nettoyer les tâches
make clean-tasks

# Redéployer après modif
make deploy-fast
```

---

## 📊 Métriques & Observabilité

### **Logs disponibles**
```bash
# Logs Cloud Run
gcloud logging read "resource.type=cloud_run_revision" --limit 50

# Logs avec corrélation
gcloud logging read "jsonPayload.correlation_id=\"xxx\"" --format json

# Erreurs uniquement
gcloud logging read "severity>=ERROR" --limit 20

# Requêtes lentes
gcloud logging read "httpRequest.latency>5s" --limit 10
```

### **Métriques Cloud Run**
- Request count (requêtes/sec)
- Request latency (p50, p95, p99)
- Container instances (scaling)
- Memory utilization
- CPU utilization
- Error rate (5xx)

### **Alertes recommandées**
```yaml
- Error rate > 5% (5min)
- Latency p95 > 10s (5min)
- Memory usage > 80% (10min)
- Scheduler job failed (1 occurrence)
- Service unavailable (1min)
```

---

## 🔐 Sécurité

### **Bonnes pratiques implémentées**
✅ Service Account dédié (pas de default SA)  
✅ Principe du moindre privilège (IAM)  
✅ Cloud Run privé (no-allow-unauthenticated)  
✅ OIDC pour authentification  
✅ Secrets via Secret Manager (pas de .env commité)  
✅ Throttling pour respecter CGU sources  
✅ User-Agent dédié et identifiable  

### **Permissions requises**
```yaml
Service Account:
  - roles/run.invoker          # Invoker Cloud Run
  - roles/cloudtasks.enqueuer  # Créer tâches
  - roles/storage.objectAdmin  # GCS (si activé)

Cloud Run:
  - Invoker: Service Account uniquement
  - No public access
```

---

## 📚 Documentation

### **Fichiers de documentation**
- **README.md** : Documentation complète (architecture, install, usage)
- **QUICKSTART.md** : Démarrage rapide en 5 minutes
- **TROUBLESHOOTING.md** : Guide dépannage détaillé (25+ cas)
- **PROJECT_STRUCTURE.md** : Vue d'ensemble (ce fichier)

### **Ressources externes**
- [Cloud Run Docs](https://cloud.google.com/run/docs)
- [Cloud Tasks Docs](https://cloud.google.com/tasks/docs)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [pytest Docs](https://docs.pytest.org/)

---

## 🎯 Points d'attention

### **À adapter selon votre contexte**
1. **Chemins GPI** : Ajuster `self.gpi_base` dans `runner.py`
2. **Sélecteurs HTML** : Mettre à jour si ZEturf/Geny changent structure
3. **Timeouts** : Ajuster selon durée réelle des analyses
4. **Ressources** : CPU/RAM selon complexité GPI
5. **Budget** : Paramètre `GPI_BUDGET_PER_RACE` selon stratégie

### **Limitations connues**
- localStorage/sessionStorage non supporté (artifacts)
- Parsing HTML fragile (dépend structure sites)
- Rate limiting manuel (pas de queue distribuée)
- Pas de retry automatique sur parsing failures

### **Évolutions possibles**
- Dashboard FastAPI pour visualisation
- Cache Redis pour plans du jour
- Notifications Slack/Email sur erreurs
- Export BigQuery pour analytics
- API webhook pour résultats temps réel

---

## 📞 Support & Contribution

### **En cas de problème**
1. Consulter [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
2. Vérifier logs: `make logs-errors`
3. Tester healthcheck: `make test-prod`
4. Générer rapport diagnostic (voir TROUBLESHOOTING)

### **Contribution**
```bash
# 1. Fork & clone
# 2. Créer branche
git checkout -b feature/ma-feature

# 3. Développer avec tests
pytest -m unit

# 4. Commit
git commit -m "feat: description"

# 5. Push & PR
```

---

**Version** : 1.0.0  
**Dernière mise à jour** : 2025-10-16  
**Licence** : Usage éducatif uniquement

---

## 🏁 Checklist déploiement complet

- [ ] Copier tous les fichiers dans l'arborescence
- [ ] Créer `.env` depuis `.env.example`
- [ ] Remplir `PROJECT_ID`, `REGION`, `SA_EMAIL`
- [ ] Activer APIs GCP (`make setup`)
- [ ] Copier modules GPI dans `gpi_modules/`
- [ ] Ajuster chemins dans `runner.py`
- [ ] Déployer service (`make deploy`)
- [ ] Créer scheduler (`make scheduler`)
- [ ] Tester (`make test-prod`)
- [ ] Vérifier monitoring (`./scripts/monitor.sh`)
- [ ] Configurer alertes Cloud Monitoring
- [ ] Documenter spécificités projet

**🎉 Projet prêt pour production !**
