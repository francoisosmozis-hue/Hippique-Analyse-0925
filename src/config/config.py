"""Configuration module"""
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass
class Config:
    # Existing fields from original file
    project_id: str
    region: str
    service_name: str
    queue_id: str
    service_account_email: str
    tz: ZoneInfo
    gcs_bucket: str | None = None
    require_auth: bool = True
    log_level: str = "INFO"
    service_url: str | None = None
    user_agent: str = "HippiqueOrchestrator/1.0"
    requests_per_second: float = 1.0
    request_timeout: int = 10
    max_retries: int = 3
    environment: str = "production"

    # New fields from user request
    timeout_seconds: int = 600
    budget_per_race: float = 5.0
    gcs_prefix: str = "hippique"
    payout_calibration_path: str = "config/payout_calibration.yaml"
    drive_folder_id: str | None = None

    @classmethod
    def from_env(cls) -> "Config":
        tz_str = os.getenv("TZ", "Europe/Paris")
        return cls(
            # Existing
            project_id=os.getenv("PROJECT_ID", "analyse-hippique"),
            region=os.getenv("REGION", "europe-west1"),
            service_name=os.getenv("SERVICE_NAME", "hippique-orchestrator"),
            queue_id=os.getenv("QUEUE_ID", "hippique-tasks"),
            service_account_email=os.getenv("SERVICE_ACCOUNT_EMAIL", ""),
            tz=ZoneInfo(tz_str),
            gcs_bucket=os.getenv("GCS_BUCKET"),
            require_auth=os.getenv("REQUIRE_AUTH", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            service_url=os.getenv("SERVICE_URL"),
            user_agent=os.getenv("USER_AGENT", "HippiqueOrchestrator/1.0"),
            requests_per_second=float(os.getenv("REQUESTS_PER_SECOND", "1.0")),
            request_timeout=int(os.getenv("REQUEST_TIMEOUT", "10")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            environment=os.getenv("ENVIRONMENT", "production"),

            # New
            timeout_seconds=int(os.getenv("TIMEOUT_SECONDS", "600")),
            budget_per_race=float(os.getenv("BUDGET_PER_RACE", "5.0")),
            gcs_prefix=os.getenv("GCS_PREFIX", "hippique"),
            payout_calibration_path=os.getenv("PAYOUT_CALIBRATION_PATH", "config/payout_calibration.yaml"),
            drive_folder_id=os.getenv("DRIVE_FOLDER_ID") or None,
        )

config = Config.from_env()
