<<<<<<< HEAD
"""
src/config.py - Configuration Centralisée

Charge les variables d'environnement et expose un singleton Config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env file if exists
load_dotenv()

@dataclass(frozen=True)
class Config:
    """Configuration immutable (singleton)"""
    
    # GCP
    project_id: str
    region: str
    service_name: str
    service_url: str
    service_account_email: str
    queue_id: str
    
    # Timezone
    timezone: str
    
    # Security
    require_auth: bool
    
    # HTTP
    user_agent: str
    requests_per_second: float
    timeout_seconds: int
    
    # GCS (optional)
    gcs_bucket: Optional[str]
    gcs_prefix: str
    
    # GPI
    budget_per_race: float
    
    # Environment
    environment: str
    
    @classmethod
    def from_env(cls) -> Config:
        """Create Config from environment variables"""
        
        # Required variables
        project_id = os.getenv("PROJECT_ID")
        if not project_id:
            raise ValueError("PROJECT_ID environment variable is required")
        
        region = os.getenv("REGION", "europe-west1")
        service_name = os.getenv("SERVICE_NAME", "hippique-orchestrator")
        queue_id = os.getenv("QUEUE_ID", "hippique-tasks")
        
        # Service URL (required for Cloud Tasks)
        service_url = os.getenv("SERVICE_URL")
        if not service_url:
            # Try to construct from service name and region
            service_url = f"https://{service_name}-<HASH>-{region}.run.app"
        
        service_account_email = os.getenv(
            "SERVICE_ACCOUNT_EMAIL",
            f"{service_name}@{project_id}.iam.gserviceaccount.com"
        )
        
        # Timezone
        timezone = os.getenv("TZ", "Europe/Paris")
        
        # Security
        require_auth = os.getenv("REQUIRE_AUTH", "true").lower() == "true"
        
        # HTTP
        user_agent = os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Hippique-Orchestrator/2.0)"
        )
        requests_per_second = float(os.getenv("REQUESTS_PER_SECOND", "1.0"))
        timeout_seconds = int(os.getenv("TIMEOUT_SECONDS", "600"))
        
        # GCS (optional)
        gcs_bucket = os.getenv("GCS_BUCKET")
        gcs_prefix = os.getenv("GCS_PREFIX", "prod/snapshots")
        
        # GPI
        budget_per_race = float(os.getenv("BUDGET_PER_RACE", "5.0"))
        
        # Environment
        environment = os.getenv("ENVIRONMENT", "production")
        
        return cls(
            project_id=project_id,
            region=region,
            service_name=service_name,
            service_url=service_url,
            service_account_email=service_account_email,
            queue_id=queue_id,
            timezone=timezone,
            require_auth=require_auth,
            user_agent=user_agent,
            requests_per_second=requests_per_second,
            timeout_seconds=timeout_seconds,
            gcs_bucket=gcs_bucket,
            gcs_prefix=gcs_prefix,
            budget_per_race=budget_per_race,
            environment=environment,
        )

# Singleton instance
_config: Optional[Config] = None

def get_config() -> Config:
    """Get or create singleton Config instance"""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config
=======
"""Configuration module"""
import os
from dataclasses import dataclass
from typing import Optional
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
    gcs_bucket: Optional[str] = None
    require_auth: bool = True
    log_level: str = "INFO"
    service_url: Optional[str] = None
    user_agent: str = "HippiqueOrchestrator/1.0"
    request_timeout: int = 10
    max_retries: int = 3
    environment: str = "production"

    # New fields from user request
    timeout_seconds: int = 600
    budget_per_race: float = 5.0
    gcs_prefix: str = "hippique"
    payout_calibration_path: str = "config/payout_calibration.yaml"
    drive_folder_id: Optional[str] = None

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
>>>>>>> ef632c0 (feat: Refactor EV calculator and clean up git repository)
