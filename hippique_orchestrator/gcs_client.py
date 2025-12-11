"""
Utilities for interacting with Google Cloud Storage (GCS).
"""
import logging
from functools import cache

import gcsfs
from google.cloud import storage

from hippique_orchestrator.config import get_config

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
        config = get_config()
        self._bucket_name = bucket_name or config.GCS_BUCKET
        if not self._bucket_name:
            logger.warning(
                "GCS_BUCKET is not set in the configuration. "
                "GCS operations will fail."
            )
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

@cache
def get_gcs_manager() -> GCSManager | None:
    """
    Returns a singleton instance of the GCSManager, creating it on first call.
    This deferred initialization helps prevent circular import issues.
    """
    config = get_config()
    if not config.USE_GCS:
        logger.info("GCS operations are disabled via configuration (USE_GCS=False).")
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
