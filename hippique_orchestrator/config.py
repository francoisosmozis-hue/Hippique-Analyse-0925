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
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET")

# --- Variables manquantes ajoutées ---
REQUIRE_AUTH = True # Hardcode for debugging
BUDGET_CAP_EUR = float(os.getenv("BUDGET_CAP_EUR", "5.0"))
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION", "races-dev")

# Task Scheduling Offsets
h30_offset = timedelta(minutes=30)
h5_offset = timedelta(minutes=5)


# Retry/Fallback Configuration for HTTP requests
RETRIES = int(os.getenv("RETRIES", "2"))  # 2 retries = 3 total attempts
TIMEOUT_S = int(os.getenv("TIMEOUT_S", "8"))
BACKOFF_BASE_S = float(os.getenv("BACKOFF_BASE_S", "1.0"))
