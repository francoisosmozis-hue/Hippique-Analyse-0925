"""
src/config.py - Configuration centralisée du service
"""

from __future__ import annotations

import logging
from functools import lru_cache

import google.auth
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Config(BaseSettings):
    """
    Configuration centralisée du service hippique-orchestrator.
    Les valeurs sont chargées depuis les variables d'environnement ou un fichier .env.
    """

    model_config = SettingsConfigDict(
        env_file=None, # Ensure .env files are not loaded, prioritizing environment variables
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- GCP Configuration ---
    PROJECT_ID: str = Field(default_factory=lambda: google.auth.default()[1])
    REGION: str = "europe-west1"
    SERVICE_NAME: str = "hippique-orchestrator"
    QUEUE_ID: str = "hippique-tasks-v2"
    SERVICE_ACCOUNT_EMAIL: str | None = None
    GCS_BUCKET: str = "analyse-hippique-data"

    # --- Application Configuration ---
    LOG_LEVEL: str = "DEBUG"
    TZ: str = "Europe/Paris"
    DEBUG: bool = True

    # --- Security ---
    REQUIRE_AUTH: bool = True
    OIDC_AUDIENCE: str | None = None
    CLOUD_RUN_URL: str | None = None

    # --- Public Paths (for Auth Middleware) ---
    PUBLIC_PATHS: list[str] = Field(
        default=[
            "/ping",
            "/health",
            "/docs",
            "/openapi.json",
            "/api/pronostics",
            "/api/pronostics/ui",
            "/api/schedule/next",
        ]
    )


    # --- Performance & Rate Limiting ---
    MAX_RETRIES: int = 3
    TIMEOUT_SECONDS: int = 600
    REQUESTS_PER_SECOND: float = 1.0
    USER_AGENT: str = "HippiqueAnalyzer/5.1 (+contact@yourdomain.com)"

    # --- Business Logic: GPI v5.1 ---
    BUDGET_TOTAL: float = 5.0
    SP_RATIO: float = 0.6
    COMBO_RATIO: float = 0.4
    EV_MIN_GLOBAL: float = 0.40
    ROI_MIN_GLOBAL: float = 0.25
    EV_MIN_SP: float = 0.15
    MAX_COMBO_OVERROUND: float = 1.30

    # --- Feature Flags & Paths ---
    SCHEDULING_MODE: str = "tasks"  # "tasks" or "local"
    GCS_PREFIX: str = "prod"
    TICKETS_BUCKET: str = "analyse-hippique-tickets"
    TICKETS_PREFIX: str = "tickets"
    CALIB_PATH: str | None = None
    SOURCES_FILE: str | None = None
    RUNNER_SNAP_DIR: str | None = None
    RUNNER_ANALYSIS_DIR: str | None = None
    RUNNER_OUTPUT_DIR: str | None = None
    USE_GCS: bool = True
    USE_FIRESTORE: bool = True
    USE_DRIVE: bool = False

    @property
    def cloud_run_url(self) -> str:
        """Constructs the Cloud Run service URL."""
        if self.OIDC_AUDIENCE:
            return self.OIDC_AUDIENCE
        # Assume https for Cloud Run URLs
        return f"https://{self.SERVICE_NAME}-{self.PROJECT_ID}.a.run.app"

    @property
    def queue_path(self) -> str:
        """Constructs the full Cloud Tasks queue path."""
        return f"projects/{self.PROJECT_ID}/locations/{self.REGION}/queues/{self.QUEUE_ID}"


@lru_cache
def get_config() -> Config:
    """
    Returns the singleton configuration object.
    The lru_cache decorator ensures the Config object is created only once.
    """
    logger.info("Loading configuration...")
    try:
        config = Config()
        # Log a subset of the config for debugging, avoiding sensitive values
        logger.info(
            ("Configuration loaded: PROJECT_ID=%s, GCS_BUCKET=%s, MODE=%s"),
            config.PROJECT_ID,
            config.GCS_BUCKET,
            config.SCHEDULING_MODE,
        )
        return config
    except Exception as e:
        logger.critical(f"Failed to load configuration: {e}", exc_info=True)
        raise


def reload_config() -> Config:
    """
    Clears the cache, forcing a reload of the configuration on the next get_config() call.
    """
    get_config.cache_clear()
    logger.info("Configuration cache cleared. Will reload on next request.")
    return get_config()
