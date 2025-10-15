"""Configuration management for Cloud Run service."""
import os
from zoneinfo import ZoneInfo
from typing import Optional


class Config:
    """Application configuration from environment."""
    
    def __init__(self):
        # GCP
        self.PROJECT_ID = os.getenv("PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
        self.REGION = os.getenv("REGION", "europe-west1")
        self.SERVICE_NAME = os.getenv("SERVICE_NAME", "hippique-orchestrator")
        self.SERVICE_URL = os.getenv("SERVICE_URL", f"https://{self.SERVICE_NAME}-{self.REGION}.run.app")
        
        # Cloud Tasks
        self.QUEUE_ID = os.getenv("QUEUE_ID", "hippique-tasks")
        self.QUEUE_LOCATION = os.getenv("QUEUE_LOCATION", self.REGION)
        
        # Storage
        self.GCS_BUCKET = os.getenv("GCS_BUCKET", "")
        self.GCS_PREFIX = os.getenv("GCS_PREFIX", "")
        
        # Security
        self.REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "true").lower() == "true"
        self.SERVICE_ACCOUNT = os.getenv("SERVICE_ACCOUNT", "")
        
        # Timezone
        self.TZ = ZoneInfo("Europe/Paris")
        self.UTC = ZoneInfo("UTC")
        
        # Data paths
        self.DATA_DIR = os.getenv("DATA_DIR", "/tmp/data")
        self.CALIBRATION_PATH = os.getenv("CALIBRATION_PATH", "calibration/payout_calibration.yaml")
        
        # GPI parameters
        self.BUDGET = float(os.getenv("BUDGET", "5.0"))
        self.EV_MIN = float(os.getenv("EV_MIN", "0.40"))
        self.ROI_MIN = float(os.getenv("ROI_MIN", "0.25"))
        
    def validate(self):
        """Validate required configuration."""
        if not self.PROJECT_ID:
            raise ValueError("PROJECT_ID or GOOGLE_CLOUD_PROJECT required")
        if not self.SERVICE_NAME:
            raise ValueError("SERVICE_NAME required")
