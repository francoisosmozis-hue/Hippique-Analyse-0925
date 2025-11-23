"""
src/config.py - Configuration centralisée du service
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

from src.logging_utils import get_logger

# Charger .env si présent
load_dotenv()

# Configurer le logging de base pour s'assurer que les messages sont visibles
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class AppConfig:
    """Configuration du service hippique-orchestrator."""

    # GCP
    project_id: str
    region: str
    service_url: str
    cloud_tasks_queue: str
    cloud_tasks_sa_email: str

    # Sécurité
    require_auth: bool

    # Application
    log_level: str
    environment: str
    payout_calibration_path: str

    # GPI v5.1
    h30_offset: timedelta
    h5_offset: timedelta

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Factory method to create AppConfig from environment variables."""
        load_dotenv()
        
        payout_calibration_path = os.getenv("PAYOUT_CALIBRATION_PATH", "config/payout_calibration.yaml")
        if not Path(payout_calibration_path).exists():
            logger.warning(f"Payout calibration file not found at {payout_calibration_path}.")

        is_testing = "PYTEST_CURRENT_TEST" in os.environ
        
        cloud_tasks_sa_email = os.getenv("CLOUD_TASKS_SA_EMAIL")
        if not cloud_tasks_sa_email:
            if is_testing:
                logger.warning("Test environment detected: using a dummy CLOUD_TASKS_SA_EMAIL.")
                cloud_tasks_sa_email = "test-invoker@example.com"
            else:
                raise ValueError("CLOUD_TASKS_SA_EMAIL environment variable is required in non-test environments.")

        return cls(
            project_id=os.getenv("GCP_PROJECT_ID", "local-project"),
            region=os.getenv("GCP_REGION", "local-region"),
            service_url=os.getenv("CLOUD_RUN_SERVICE_URL", "http://localhost:8080"),
            cloud_tasks_queue=os.getenv("CLOUD_TASKS_QUEUE", "hippique-analysis-queue"),
            cloud_tasks_sa_email=cloud_tasks_sa_email,
            require_auth=os.getenv("REQUIRE_AUTH", "false").lower() in ("true", "1"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            payout_calibration_path=payout_calibration_path,
            h30_offset=timedelta(minutes=int(os.getenv("H30_OFFSET_MINUTES", 30))),
            h5_offset=timedelta(minutes=int(os.getenv("H5_OFFSET_MINUTES", 5))),
            environment=os.getenv("ENVIRONMENT", "local"),
        )

    @property
    def queue_path(self) -> str:
        """Chemin complet de la queue Cloud Tasks."""
        return f"projects/{self.project_id}/locations/{self.region}/queues/{self.cloud_tasks_queue}"


# Singleton global
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Retourne la configuration singleton."""
    global _config
    if _config is None:
        _config = AppConfig.from_env()
    return _config


def reload_config() -> AppConfig:
    """Force le rechargement de la configuration."""
    global _config
    _config = None
    return get_config()
