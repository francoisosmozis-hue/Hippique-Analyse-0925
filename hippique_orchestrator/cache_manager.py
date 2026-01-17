"""
Manages caching operations, currently with a GCS backend.

This module abstracts the storage backend (Google Cloud Storage) for caching
and retrieving data like race programs and analysis results. It is designed
to be the single point of contact for any cache-related operations.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Optional
import os

from google.cloud import storage
from hippique_orchestrator import config
from hippique_orchestrator.data_contract import Programme
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)


class CacheManager:
    """A class to manage caching operations with a pluggable backend."""

    def __init__(self, client: Optional[storage.Client] = None):
        self._client = client

    @property
    def client(self) -> storage.Client:
        """
        Provides a GCS client, initializing it if it doesn't exist.
        This lazy initialization is crucial for offline testing where a client
        may not be available or needed.
        """
        if self._client is None:
            if not self.is_enabled():
                raise ConnectionError(
                    "CacheManager is disabled, cannot create GCS client."
                )
            try:
                self._client = storage.Client()
            except Exception as e:
                logger.error(f"Failed to initialize GCS client: {e}", exc_info=e)
                raise ConnectionError("Failed to initialize GCS client.") from e
        return self._client

    @staticmethod
    def is_enabled() -> bool:
        """Checks if the GCS caching backend is configured and enabled."""
        return bool(config.BUCKET_NAME)

    def get_programme_path(self, target_date: date) -> str:
        """Constructs the GCS path for a given day's programme."""
        date_str = target_date.strftime("%Y-%m-%d")
        return f"{config.GCS_PROGRAMME_PREFIX}/{date_str}.json"

    def save_programme(self, programme: Programme, target_date: date) -> None:
        """
        Saves a Programme object to the cache.

        Args:
            programme: The Programme object to save.
            target_date: The date of the programme.
        """
        if not self.is_enabled():
            logger.debug("Cache is disabled. Skipping save_programme.")
            return

        gcs_path = self.get_programme_path(target_date)
        try:
            bucket = self.client.bucket(config.BUCKET_NAME)
            blob = bucket.blob(gcs_path)
            
            # Use Pydantic's serialization feature
            programme_data = programme.model_dump_json(indent=4)

            blob.upload_from_string(programme_data, content_type="application/json")
            logger.info(
                f"Successfully saved programme for {target_date} to "
                f"gs://{config.BUCKET_NAME}/{gcs_path}"
            )
        except Exception as e:
            logger.error(
                f"Failed to save programme for {target_date} to GCS: {e}", exc_info=e
            )

    def load_programme(self, target_date: date) -> Optional[Programme]:
        """
        Loads a Programme object from the cache for a given date.

        Args:
            target_date: The date of the programme to load.

        Returns:
            A Programme object if found in cache, otherwise None.
        """
        if not self.is_enabled():
            logger.debug("Cache is disabled. Skipping load_programme.")
            return None

        gcs_path = self.get_programme_path(target_date)
        try:
            bucket = self.client.bucket(config.BUCKET_NAME)
            blob = bucket.blob(gcs_path)

            if not blob.exists():
                logger.info(
                    f"Programme for {target_date} not found in cache at {gcs_path}."
                )
                return None

            programme_data = blob.download_as_string()
            
            # Use Pydantic's parsing feature for validation
            programme = Programme.model_validate_json(programme_data)
            
            logger.info(
                f"Successfully loaded programme for {target_date} from "
                f"gs://{config.BUCKET_NAME}/{gcs_path}"
            )
            return programme

        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to decode JSON for programme {target_date} from GCS: {e}",
                exc_info=True,
            )
            return None
        except Exception as e:
            logger.error(
                f"Failed to load programme for {target_date} from GCS: {e}",
                exc_info=True,
            )
            return None

# Create a singleton instance for convenient access across the application
cache_manager = CacheManager()
