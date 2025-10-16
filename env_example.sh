# .env.example - Configuration Template
# Copy to .env and fill with your values

# ============================================
# GCP Configuration (REQUIRED)
# ============================================

# Your GCP project ID
PROJECT_ID=analyse-hippique

# GCP region for Cloud Run and Cloud Tasks
REGION=europe-west1

# Cloud Run service name
SERVICE_NAME=hippique-orchestrator

# Cloud Run service URL (fill after first deployment)
SERVICE_URL=https://hippique-orchestrator-1084663881709.europe-west4.run.app

# Service account email for authentication
SERVICE_ACCOUNT_EMAIL=hippique-orchestrator@analyse-hippique.iam.gserviceaccount.com

# Cloud Tasks queue ID
QUEUE_ID=hippique-tasks

# ============================================
# Timezone
# ============================================

# Timezone for race times (DO NOT CHANGE)
TZ=Europe/Paris

# ============================================
# Security
# ============================================

# Require OIDC authentication (true for production)
REQUIRE_AUTH=true

# ============================================
# HTTP Configuration
# ============================================

# User-Agent for HTTP requests
USER_AGENT=Mozilla/5.0 (Hippique-Orchestrator/2.0)

# Rate limiting (requests per second per host)
REQUESTS_PER_SECOND=1.0

# Subprocess timeout in seconds
TIMEOUT_SECONDS=600

# ============================================
# Google Cloud Storage (OPTIONAL)
# ============================================

# GCS bucket for artifact storage (leave empty to disable)
GCS_BUCKET=

# GCS path prefix
GCS_PREFIX=prod/snapshots

# ============================================
# GPI Configuration
# ============================================

# Budget per race (euros)
BUDGET_PER_RACE=5.0

# ============================================
# Environment
# ============================================

# Environment name (development, staging, production)
ENVIRONMENT=production

# Gunicorn workers (2 recommended for Cloud Run)
GUNICORN_WORKERS=2

# Gunicorn timeout (same as TIMEOUT_SECONDS)
GUNICORN_TIMEOUT=600

# Log level (debug, info, warning, error)
LOG_LEVEL=info
