import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Configuration centralisée depuis variables d'environnement."""

    project_id: str
    region: str
    service_name: str
    queue_id: str
    scheduler_sa_email: str
    port: int = 8080
    timezone: str = "Europe/Paris"
    require_auth: bool = True
    gcs_bucket: Optional[str] = None
    user_agent: str = "GPI-Hippique-Analyzer/5.1 (+compliance @example.com)"
    request_timeout: int = 30
    max_retries: int = 3
    rate_limit_delay: float = 1.1
    budget_per_race: float = 5.0
    min_ev_threshold: float = 40.0

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            project_id=os.getenv("PROJECT_ID", ""),
            region=os.getenv("REGION", "europe-west1"),
            service_name=os.getenv("SERVICE_NAME", "hippique-analyzer"),
            queue_id=os.getenv("QUEUE_ID", "race-analysis-queue"),
            scheduler_sa_email=os.getenv("SCHEDULER_SA_EMAIL", ""),
            port=int(os.getenv("PORT", "8080")),
            timezone=os.getenv("TZ", "Europe/Paris") ,
            require_auth=os.getenv("REQUIRE_AUTH", "true").lower() == "true",
            gcs_bucket=os.getenv("GCS_BUCKET") ,
        )

    @property
    def service_url(self) -> str:
        return f"https://{self.service_name}-{self.region}.run.app"
