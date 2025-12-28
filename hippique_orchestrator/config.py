# hippique_orchestrator/config.py
import os

from dotenv import load_dotenv

load_dotenv()

# GCP Configuration
PROJECT_ID = os.getenv("PROJECT_ID")
LOCATION = os.getenv("LOCATION", "europe-west1")
BUCKET_NAME = os.getenv("BUCKET_NAME")

# Cloud Tasks Configuration
TASK_QUEUE = os.getenv("TASK_QUEUE", os.getenv("CLOUD_TASKS_QUEUE", "hippique-tasks-queue"))
# Service Account pour signer les jetons OIDC (doit avoir le rôle 'Service Account Token Creator')
TASK_OIDC_SA_EMAIL = os.getenv("TASK_OIDC_SA_EMAIL")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Business Logic: GPI v5.1
EV_MIN_SP = float(os.getenv("EV_MIN_SP", "0.15"))
EV_MIN_GLOBAL = float(os.getenv("EV_MIN_GLOBAL", "0.40"))
ROI_MIN_GLOBAL = float(os.getenv("ROI_MIN_GLOBAL", "0.25"))
MAX_COMBO_OVERROUND = float(os.getenv("MAX_COMBO_OVERROUND", "1.30"))

# Secret key for internal API authentication
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET")
