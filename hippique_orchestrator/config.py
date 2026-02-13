# hippique_orchestrator/config.py
import os
from datetime import timedelta

# GCP Configuration
PROJECT_ID = os.getenv("PROJECT_ID")
LOCATION = os.getenv("LOCATION", "europe-west1")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# Cloud Tasks Configuration
TASK_QUEUE = os.getenv("TASK_QUEUE", os.getenv("CLOUD_TASKS_QUEUE", "hippique-tasks-queue"))
# Service Account pour signer les jetons OIDC (doit avoir le rôle 'Service Account Token Creator')
TASK_OIDC_SA_EMAIL = os.getenv("TASK_OIDC_SA_EMAIL")
LOG_LEVEL = "DEBUG" # Hardcode for debugging
TIMEZONE = os.getenv("TIMEZONE", "Europe/Paris")

# Business Logic: GPI v5.1
EV_MIN_SP = float(os.getenv("EV_MIN_SP", "0.15"))
EV_MIN_GLOBAL = float(os.getenv("EV_MIN_GLOBAL", "0.40"))
ROI_MIN_GLOBAL = float(os.getenv("ROI_MIN_GLOBAL", "0.25"))
MAX_COMBO_OVERROUND = float(os.getenv("MAX_COMBO_OVERROUND", "1.30"))

# Task concurrency
MAX_CONCURRENT_SNAPSHOT_TASKS = int(os.getenv("MAX_CONCURRENT_SNAPSHOT_TASKS", "5"))

# GCS Enablement for local dev/test
GCS_ENABLED = os.getenv("GCS_ENABLED", "False").lower() in ("true", "1", "t")

# Secret key for internal API authentication
_secret_path = "/run/secrets/hippique-internal-api-secret-v1"
if os.path.exists(_secret_path):
    with open(_secret_path, "r") as f:
        INTERNAL_API_SECRET = f.read().strip()
else:
    INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET")

# --- Variables manquantes ajoutées ---
# Determine if authentication is required based on the environment
REQUIRE_AUTH = os.getenv("ENV_NAME") == "production"
BUDGET_CAP_EUR = float(os.getenv("BUDGET_CAP_EUR", "5.0"))
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION", "races")

# Task Scheduling Offsets
h30_offset = timedelta(minutes=30)
h5_offset = timedelta(minutes=5)
