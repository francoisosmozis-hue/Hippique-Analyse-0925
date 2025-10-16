# ============================================================================
# CONFIGURATION ORCHESTRATEUR HIPPIQUE - CLOUD RUN
# ============================================================================
# Copier ce fichier en .env et remplir les valeurs

# ----------------------------------------------------------------------------
# GCP Project & Region
# ----------------------------------------------------------------------------
PROJECT_ID=your-gcp-project-id
REGION=europe-west1
SERVICE_NAME=horse-racing-orchestrator

# URL du service Cloud Run (rempli après déploiement)
SERVICE_URL=https://horse-racing-orchestrator-xxxxx-ew.a.run.app

# ----------------------------------------------------------------------------
# Cloud Tasks & Scheduler
# ----------------------------------------------------------------------------
# Nom de la queue Cloud Tasks
QUEUE_ID=horse-racing-queue

# Service Account pour Scheduler/Tasks (format: name@project.iam.gserviceaccount.com)
SCHEDULER_SA_EMAIL=scheduler-sa@your-project.iam.gserviceaccount.com

# Nom du job quotidien 09:00
SCHEDULER_JOB_0900=daily-plan-0900

# ----------------------------------------------------------------------------
# Authentification & Sécurité
# ----------------------------------------------------------------------------
# Activer la vérification OIDC (true pour production)
REQUIRE_AUTH=true

# Audience OIDC (généralement = SERVICE_URL)
OIDC_AUDIENCE=

# ----------------------------------------------------------------------------
# Storage
# ----------------------------------------------------------------------------
# Bucket GCS pour archiver artefacts (optionnel)
GCS_BUCKET=your-bucket-name

# Répertoire local dans le conteneur
LOCAL_DATA_DIR=/tmp/horse_data

# ----------------------------------------------------------------------------
# Timezone & Planification
# ----------------------------------------------------------------------------
# Timezone pour calculs (ne pas changer)
TIMEZONE=Europe/Paris

# Heure du déclenchement quotidien (format 24h)
DAILY_SCHEDULE_HOUR=9

# ----------------------------------------------------------------------------
# Throttling & Retries
# ----------------------------------------------------------------------------
# Timeout requêtes HTTP (secondes)
REQUEST_TIMEOUT=30

# Nombre de retries en cas d'échec
MAX_RETRIES=3

# Délai entre requêtes (secondes) - respect CGU
RATE_LIMIT_DELAY=1.0

# User-Agent pour requêtes HTTP
USER_AGENT=HorseRacingAnalyzer/5.1 (Educational; contact@example.com)

# ----------------------------------------------------------------------------
# Paramètres GPI (Gestion Pronostique Intelligente)
# ----------------------------------------------------------------------------
# Budget maximum par course (euros)
GPI_BUDGET_PER_RACE=5.0

# Espérance de Valeur minimale pour combos (%)
GPI_MIN_EV_PERCENT=40.0

# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
# Niveau de log (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO

# ----------------------------------------------------------------------------
# Gunicorn (optionnel, par défaut dans gunicorn.conf.py)
# ----------------------------------------------------------------------------
# Nombre de workers
WORKERS=2

# Port (défini par Cloud Run)
PORT=8080
