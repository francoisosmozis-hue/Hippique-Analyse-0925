"""Application configuration helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables."""

    project_id: str = Field("", alias="PROJECT_ID")
    region: str = Field("europe-west1", alias="REGION")
    service_name: str = Field("hippique-analyse", alias="SERVICE_NAME")
    queue_id: str = Field("hippique-run-queue", alias="QUEUE_ID")
    timezone: str = Field("Europe/Paris", alias="TZ")
    service_url: str = Field("", alias="SERVICE_URL")
    service_audience: str = Field("", alias="SERVICE_AUDIENCE")
    require_auth: bool = Field(False, alias="REQUIRE_AUTH")
    gcs_bucket: str = Field("", alias="GCS_BUCKET")
    gcs_prefix: str = Field("", alias="GCS_PREFIX")
    data_dir: Path = Field(Path("data/runtime"), alias="DATA_DIR")
    http_user_agent: str = Field(
        "Hippique-Analyse/1.0 (+https://cloud.run/hippique)", alias="HTTP_USER_AGENT"
    )
    tasks_service_account_email: str = Field("", alias="TASKS_SERVICE_ACCOUNT_EMAIL")
    scheduler_service_account_email: str = Field("", alias="SCHEDULER_SERVICE_ACCOUNT_EMAIL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def queue_path(self) -> str:
        return f"projects/{self.project_id}/locations/{self.region}/queues/{self.queue_id}"

    @property
    def scheduler_parent(self) -> str:
        return f"projects/{self.project_id}/locations/{self.region}"

    @property
    def resolved_data_dir(self) -> Path:
        return Path(self.data_dir).resolve()

    @property
    def plan_path(self) -> Path:
        directory = self.resolved_data_dir
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "plan.json"

    @property
    def resolved_service_url(self) -> str | None:
        return self.service_url or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the application settings (cached)."""

    settings = Settings()
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    return settings
