"""
src/config.py - Configuration centralisée du service
"""

from __future__ import annotations

import os
from dataclasses import dataclass
import logging

from dotenv import load_dotenv

# Charger .env si présent
load_dotenv()


logger = logging.getLogger(__name__)

@dataclass
class Config:
    """Configuration du service hippique-orchestrator."""

    # GCP
    project_id: str
    region: str
    service_name: str
    queue_id: str
    service_account_email: str | None

    # Timezone
    timezone: str = "Europe/Paris"

    # Storage
    gcs_bucket: str | None = None
    gcs_prefix: str = "prod"

    # Sécurité
    require_auth: bool = True
    oidc_audience: str | None = None

    # Application
    log_level: str = "INFO"
    max_retries: int = 3
    timeout_seconds: int = 600

    # Rate limiting
    requests_per_second: float = 1.0
    user_agent: str = "HippiqueAnalyzer/5.1 (+contact@yourdomain.com)"

    # GPI v5.1
    budget_total: float = 5.0
    sp_ratio: float = 0.6
    combo_ratio: float = 0.4
    ev_min_global: float = 0.40
    roi_min_global: float = 0.25

    # Modes
    mode: str = "tasks"  # "tasks" ou "scheduler"

    @classmethod
    def from_env(cls) -> Config:
        """Construit la configuration depuis les variables d'environnement."""

        # Obligatoires
        project_id = os.getenv("PROJECT_ID")
        if not project_id:
            raise ValueError("PROJECT_ID environment variable is required")

        region = os.getenv("REGION", "europe-west1")
        service_name = os.getenv("SERVICE_NAME", "hippique-orchestrator")
        queue_id = os.getenv("QUEUE_ID", "hippique-tasks")
        service_account_email = os.getenv("SERVICE_ACCOUNT_EMAIL", None)
        if service_account_email is None:
            logger.warning("SERVICE_ACCOUNT_EMAIL environment variable is not set. GCS operations may fail.")

        # Optionnelles
        timezone = os.getenv("TZ", "Europe/Paris")
        gcs_bucket = os.getenv("GCS_BUCKET")
        gcs_prefix = os.getenv("GCS_PREFIX", "prod")

        require_auth = os.getenv("REQUIRE_AUTH", "true").lower() in ("true", "1", "yes")
        oidc_audience = os.getenv("OIDC_AUDIENCE")

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        max_retries = int(os.getenv("MAX_RETRIES", "3"))
        timeout_seconds = int(os.getenv("TIMEOUT_SECONDS", "600"))

        requests_per_second = float(os.getenv("REQUESTS_PER_SECOND", "1.0"))
        user_agent = os.getenv(
            "USER_AGENT",
            "HippiqueAnalyzer/5.1 (+contact@yourdomain.com)"
        )

        budget_total = float(os.getenv("BUDGET_TOTAL", "5.0"))
        sp_ratio = float(os.getenv("SP_RATIO", "0.6"))
        combo_ratio = float(os.getenv("COMBO_RATIO", "0.4"))
        ev_min_global = float(os.getenv("EV_MIN_GLOBAL", "0.40"))
        roi_min_global = float(os.getenv("ROI_MIN_GLOBAL", "0.25"))

        mode = os.getenv("SCHEDULING_MODE", "tasks")

        return cls(
            project_id=project_id,
            region=region,
            service_name=service_name,
            queue_id=queue_id,
            service_account_email=service_account_email,
            timezone=timezone,
            gcs_bucket=gcs_bucket,
            gcs_prefix=gcs_prefix,
            require_auth=require_auth,
            oidc_audience=oidc_audience,
            log_level=log_level,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            requests_per_second=requests_per_second,
            user_agent=user_agent,
            budget_total=budget_total,
            sp_ratio=sp_ratio,
            combo_ratio=combo_ratio,
            ev_min_global=ev_min_global,
            roi_min_global=roi_min_global,
            mode=mode,
        )

    @property
    def cloud_run_url(self) -> str:
        """URL du service Cloud Run."""
        if self.oidc_audience:
            return self.oidc_audience
        return f"https://{self.service_name}-{self.project_id}.{self.region}.run.app"

    @property
    def queue_path(self) -> str:
        """Chemin complet de la queue Cloud Tasks."""
        return f"projects/{self.project_id}/locations/{self.region}/queues/{self.queue_id}"

    @property
    def is_gcs_configured(self) -> bool:
        return self.gcs_bucket is not None and self.service_account_email is not None


# Singleton global
_config: Config | None = None


def get_config() -> Config:
    """Retourne la configuration singleton."""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def reload_config() -> Config:
    """Force le rechargement de la configuration."""
    global _config
    _config = None
    return get_config()
