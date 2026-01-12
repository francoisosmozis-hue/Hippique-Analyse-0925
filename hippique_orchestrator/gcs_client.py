import json
import logging
import os
import glob
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
        self._gcs_enabled = config.GCS_ENABLED # Store GCS_ENABLED status

        if not self._gcs_enabled:
            logger.info("GCS operations are explicitly disabled by configuration.")
            # We don't raise an error if GCS is disabled, to allow local fallback.
            # Client/FS will remain None and methods will check _gcs_enabled.
            self._client = None
            self._fs = None
            return
        
        if not self._bucket_name:
            logger.warning("GCS_BUCKET is not set in the configuration, but GCS_ENABLED is True. GCS operations will fail.")
            raise ValueError("GCS_BUCKET must be set when GCS_ENABLED is True.")

        self._client = None
        self._fs = None

    @property
    def client(self):
        """Lazy initialization of the GCS client."""
        if not self._gcs_enabled:
            raise RuntimeError("GCS is disabled. Cannot get GCS client.")
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
        if not self._gcs_enabled:
            raise RuntimeError("GCS is disabled. Cannot get GCS filesystem.")
        if self._fs is None:
            self._fs = gcsfs.GCSFileSystem()
        return self._fs

    def get_gcs_path(self, relative_path):
        """
        Constructs a full GCS path (gs://bucket/path).
        If relative_path already starts with 'gs://', it's returned as is.
        It also handles cases where the path might accidentally include the bucket name.

        Args:
            relative_path (str): The relative path of the file or a full GCS URI.

        Returns:
            str: The full GCS path.
        """
        if relative_path.startswith("gs://"):
            return relative_path
        
        # Strip leading bucket name if it's accidentally included
        path_to_join = relative_path
        if path_to_join.startswith(self.bucket_name + "/"):
            path_to_join = path_to_join[len(self.bucket_name) + 1:]

        return f"gs://{self.bucket_name}/{path_to_join}"

    def file_exists(self, gcs_path):
        """
        Checks if a file exists in GCS.

        Args:
            gcs_path (str): The GCS path (e.g., 'gs://bucket/file.txt' or 'path/to/file.txt').

        Returns:
            bool: True if the file exists, False otherwise.
        """
        if not self._gcs_enabled:
            return False # GCS is disabled, so files don't exist in GCS

        gcs_uri = self.get_gcs_path(gcs_path)
        logger.debug(f"Checking if file exists in GCS: {gcs_uri}")
        try:
            return self.fs.exists(gcs_uri)
        except Exception as e:
            logger.error(f"Failed to check GCS file existence at {gcs_uri}: {e}", exc_info=True)
            return False

    def list_files(self, path: str) -> list[str]:
        """
        Lists files in a GCS directory.

        Args:
            path (str): The GCS path (e.g., 'gs://bucket/dir/' or 'dir/').

        Returns:
            list[str]: A list of full GCS paths of files.
        """
        if not self._gcs_enabled:
            raise RuntimeError("GCS is disabled. Cannot list files.")

        gcs_uri = self.get_gcs_path(path)
        logger.debug(f"Listing files in GCS: {gcs_uri}")
        try:
            # gcsfs.ls returns a list of dictionaries with 'name', 'type', 'size', etc.
            # We want just the full paths of files
            files_info = self.fs.ls(gcs_uri, detail=True)
            return [self.get_gcs_path(f['name']) for f in files_info if f['type'] == 'file']
        except Exception as e:
            logger.error(f"Failed to list files in GCS at {gcs_uri}: {e}", exc_info=True)
            raise

    def read_file_from_gcs(self, gcs_path: str) -> str | None:
        """
        Reads the content of a file from GCS.

        Args:
            gcs_path (str): The GCS path (e.g., 'gs://bucket/path/to/file.json' or 'path/to/file.json').

        Returns:
            str: The content of the file, or None if an error occurs.
        """
        if not self._gcs_enabled:
            raise RuntimeError("GCS is disabled. Cannot read file.")

        gcs_uri = self.get_gcs_path(gcs_path)
        logger.debug(f"Reading file from GCS: {gcs_uri}")
        try:
            with self.fs.open(gcs_uri, 'r') as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"Failed to read file from GCS at {gcs_uri}: {e}", exc_info=True)
            return None

    def save_json_to_gcs(self, gcs_path: str, data: dict[str, Any]):
        """
        Saves a dictionary as a JSON file to GCS.

        Args:
            gcs_path (str): The GCS path (e.g., 'gs://bucket/path/to/file.json' or 'path/to/file.json').
            data (dict): The dictionary to save as JSON.
        """
        if not self._gcs_enabled:
            logger.info(f"GCS is disabled. Skipping saving JSON to {gcs_path}.")
            return

        gcs_uri = self.get_gcs_path(gcs_path) # Ensure it's a full URI
        logger.info(f"Saving JSON to GCS: {gcs_uri}")
        try:
            with self.fs.open(gcs_uri, 'w') as f:
                json.dump(data, f)
            logger.info(f"Successfully saved JSON to {gcs_uri}")
        except Exception as e:
            logger.error(f"Failed to save JSON to GCS at {gcs_uri}: {e}", exc_info=True)
            raise


_gcs_manager_instance = None # Global instance to manage the singleton

def get_gcs_manager() -> GCSManager | None:
    """
    Returns a singleton instance of the GCSManager.
    """
    global _gcs_manager_instance
    logger.debug(f"Attempting to get GCSManager. GCS_ENABLED: {config.GCS_ENABLED}, BUCKET_NAME: {config.BUCKET_NAME}")
    if not config.GCS_ENABLED:
        logger.info("GCS operations are disabled because GCS_ENABLED is False.")
        _gcs_manager_instance = None # Ensure no stale manager is kept
        return None
    if not config.BUCKET_NAME:
        logger.info("GCS operations are disabled because BUCKET_NAME is not set.")
        _gcs_manager_instance = None # Ensure no stale manager is kept
        return None
    
    if _gcs_manager_instance is None:
        try:
            _gcs_manager_instance = GCSManager()
        except ValueError as e:
            logger.warning(f"Could not initialize GCSManager: {e}")
            _gcs_manager_instance = None
    return _gcs_manager_instance

def reset_gcs_manager():
    """Resets the singleton GCSManager instance. Useful for testing."""
    global _gcs_manager_instance
    _gcs_manager_instance = None

def get_gcs_fs():
    """
    Returns the GCS filesystem object from the manager.
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


def list_files(path: str) -> list[str]:
    """
    Lists files from GCS, with a local filesystem fallback if GCS is disabled.

    Args:
        path (str): The GCS path (e.g., 'gs://bucket/dir/' or 'dir/') or local path.

    Returns:
        list[str]: A list of file paths.
    """
    manager = get_gcs_manager()
    if manager and manager._gcs_enabled:
        return manager.list_files(path)
    else:
        logger.info(f"GCS disabled or manager not initialized. Listing files locally from: {path}")
        # Local fallback
        # Assuming path can be relative or absolute, and should refer to actual files
        # Example: data/R1C1/snapshots/
        local_path = path.replace("gs://", "").replace(f"{config.BUCKET_NAME}/", "")
        if not local_path.startswith("data/"): # Ensure it's in a data directory
            local_path = os.path.join("data", local_path)
        
        # Add a glob pattern to list files within the directory
        # e.g., data/R1C1/snapshots/*
        files = glob.glob(os.path.join(local_path, "*"))
        return [f for f in files if os.path.isfile(f)]


def read_file_from_gcs(gcs_path: str) -> str | None:
    """
    Reads the content of a file from GCS, with a local filesystem fallback if GCS is disabled.

    Args:
        gcs_path (str): The GCS path (e.g., 'gs://bucket/path/to/file.json') or local path.

    Returns:
        str: The content of the file, or None if an error occurs.
    """
    manager = get_gcs_manager()
    if manager and manager._gcs_enabled:
        return manager.read_file_from_gcs(gcs_path)
    else:
        logger.info(f"GCS disabled or manager not initialized. Reading file locally from: {gcs_path}")
        # Local fallback
        local_path = gcs_path.replace("gs://", "").replace(f"{config.BUCKET_NAME}/", "")
        try:
            if not os.path.exists(local_path):
                logger.warning(f"Local file not found: {local_path}")
                return None
            with open(local_path, 'r') as f:
                content = f.read()
            return content
        except Exception as e:
            logger.error(f"Failed to read local file {local_path}: {e}", exc_info=True)
            return None


def save_json_to_gcs(gcs_path: str, data: dict[str, Any]):
    """
    Saves a dictionary as a JSON file to GCS using the GCSManager.
    """
    manager = get_gcs_manager()
    if not manager:
        logger.error(f"GCSManager not initialized. Cannot save JSON to {gcs_path}.")
        raise RuntimeError("GCSManager not initialized or GCS disabled.")
    manager.save_json_to_gcs(build_gcs_path(gcs_path), data) # Use build_gcs_path here

