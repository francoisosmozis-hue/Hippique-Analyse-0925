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
TASK_HANDLER_URL = os.getenv("TASK_HANDLER_URL")
# Service Account pour signer les jetons OIDC (doit avoir le rôle 'Service Account Token Creator')
TASK_OIDC_SA_EMAIL = os.getenv("TASK_OIDC_SA_EMAIL")


# Application Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
SECRET_KEY = os.getenv("SECRET_KEY", "a_very_secret_key")
# Activer/désactiver l'authentification OIDC sur les endpoints de tâches
REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "true").lower() in ("true", "1", "t")

# Firestore
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION", "races-dev")

# Payout Calibration path
PAYOUT_CALIBRATION_PATH = os.getenv("PAYOUT_CALIBRATION_PATH") or os.getenv("CALIB_PATH") or "config/payout_calibration.yaml"

# Date settings
TIMEZONE = "Europe/Paris"

def get_service_url():
    """
    Retourne l'URL du service Cloud Run.
    Essentiel pour l'audience OIDC de Cloud Tasks.
    """
    # K_SERVICE est automatiquement injectée par Cloud Run
    service_name = os.getenv("K_SERVICE")
    if not service_name:
        print("WARN: K_SERVICE env var not found. Fallback to TASK_HANDLER_URL for local dev.")
        return TASK_HANDLER_URL

    # K_REVISION est aussi injectée, on peut construire l'URL tagguée
    # Mais l'URL stable est généralement suffisante
    # https://[SERVICE_NAME]-[PROJECT_HASH]-[REGION].a.run.app
    # On va laisser Cloud Run nous la donner via une variable d'env
    service_url = os.getenv("SERVICE_URL")
    if not service_url:
        raise ValueError("SERVICE_URL environment variable must be set in production.")
    return service_url

# Business Logic: GPI v5.1
EV_MIN_SP = float(os.getenv("EV_MIN_SP", "0.15"))
EV_MIN_GLOBAL = float(os.getenv("EV_MIN_GLOBAL", "0.40"))
ROI_MIN_GLOBAL = float(os.getenv("ROI_MIN_GLOBAL", "0.25"))
MAX_COMBO_OVERROUND = float(os.getenv("MAX_COMBO_OVERROUND", "1.30"))

# Secret key for internal API authentication
INTERNAL_API_SECRET = os.getenv("INTERNAL_API_SECRET")

