"""
Utilities for interacting with Google Cloud Storage (GCS).
"""

import json
import logging
from functools import cache
from typing import Any

import gcsfs
from google.cloud import storage

from hippique_orchestrator import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GCSManager:
    """
    A manager to handle interactions with Google Cloud Storage.
    """

    def __init__(self, bucket_name=None):
        """
        Initializes the GCSManager.

        Args:
            bucket_name (str, optional): The GCS bucket name. If not provided,
                                         it's read from the central config.
        """
        self._bucket_name = bucket_name or config.BUCKET_NAME
        if not self._bucket_name:
            logger.warning("GCS_BUCKET is not set in the configuration. GCS operations will fail.")
            raise ValueError("GCS_BUCKET must be set.")

        self._client = None
        self._fs = None

    @property
    def client(self):
        """Lazy initialization of the GCS client."""
        if self._client is None:
            self._client = storage.Client()
        return self._client

    @property
    def bucket_name(self):
        """Returns the configured bucket name."""
        return self._bucket_name

    @property
    def fs(self):
        """Lazy initialization of the gcsfs filesystem object."""
        if self._fs is None:
            self._fs = gcsfs.GCSFileSystem()
        return self._fs

    def get_gcs_path(self, relative_path):
        """
        Constructs a full GCS path (gs://bucket/path).

        Args:
            relative_path (str): The relative path of the file.

        Returns:
            str: The full GCS path.
        """
        return f"gs://{self.bucket_name}/{relative_path}"

    def file_exists(self, gcs_path):
        """
        Checks if a file exists in GCS.

        Args:
            gcs_path (str): The full GCS path (e.g., 'gs://bucket/file.txt').

        Returns:
            bool: True if the file exists, False otherwise.
        """
        return self.fs.exists(gcs_path)

    def save_json_to_gcs(self, gcs_path: str, data: dict[str, Any]):
        """
        Saves a dictionary as a JSON file to GCS.

        Args:
            gcs_path (str): The full GCS path (e.g., 'gs://bucket/path/to/file.json').
            data (dict): The dictionary to save as JSON.
        """
        logger.info(f"Saving JSON to GCS: {gcs_path}")
        try:
            with self.fs.open(gcs_path, 'w') as f:
                json.dump(data, f)
            logger.info(f"Successfully saved JSON to {gcs_path}")
        except Exception as e:
            logger.error(f"Failed to save JSON to GCS at {gcs_path}: {e}", exc_info=True)
            raise


@cache
def get_gcs_manager() -> GCSManager | None:
    """
    Returns a singleton instance of the GCSManager, creating it on first call.
    This deferred initialization helps prevent circular import issues.
    """
    if not config.BUCKET_NAME:
        logger.info("GCS operations are disabled because BUCKET_NAME is not set.")
        return None
    try:
        return GCSManager()
    except ValueError as e:
        logger.warning(f"Could not initialize GCSManager: {e}")
        return None


@cache
def get_gcs_fs():
    """
    Returns a cached instance of the GCS filesystem.
    """
    manager = get_gcs_manager()
    if manager:
        return manager.fs
    logger.error("GCSManager is not initialized. Cannot get filesystem.")
    return None


def build_gcs_path(relative_path):
    """
    Builds a full GCS path from a relative path using the manager.
    """
    manager = get_gcs_manager()
    if manager:
        return manager.get_gcs_path(relative_path)
    logger.error("GCSManager is not initialized. Cannot build GCS path.")
    return None


def save_json_to_gcs(gcs_path: str, data: dict[str, Any]):
    """
    Saves a dictionary as a JSON file to GCS using the GCSManager.
    """
    manager = get_gcs_manager()
    if not manager:
        logger.error(f"GCSManager not initialized. Cannot save JSON to {gcs_path}.")
        raise RuntimeError("GCSManager not initialized.")
    manager.save_json_to_gcs(gcs_path, data)
