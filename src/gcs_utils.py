"""GCS utilities for uploading and downloading files."""

from __future__ import annotations

import os
from pathlib import Path

from google.cloud import storage

from app_config import get_app_config
from logging_utils import get_logger

logger = get_logger(__name__)

_gcs_client = None

def _get_gcs_client():
    """Returns a GCS client, initializing it if necessary."""
    global _gcs_client
    if _gcs_client is None:
        try:
            _gcs_client = storage.Client()
        except Exception as e:
            logger.error(f"Failed to initialize GCS client: {e}", exc_info=e)
            return None
    return _gcs_client

def is_gcs_enabled() -> bool:
    """Check if GCS is enabled in the config."""
    config = get_app_config()
    return bool(config.gcs_bucket)

def disabled_reason() -> str | None:
    """Return a reason if GCS is disabled."""
    if not is_gcs_enabled():
        return "GCS_BUCKET_not_set"
    return None

def upload_file(local_path: str | os.PathLike[str]) -> None:
    """
    Upload a single file to GCS.
    """
    if not is_gcs_enabled():
        return

    config = get_app_config()
    client = _get_gcs_client()
    if not client:
        return

    try:
        bucket = client.bucket(config.gcs_bucket)
        local_file = Path(local_path)

        if not local_file.exists():
            logger.warning(f"Local file not found, cannot upload to GCS: {local_path}")
            return

        # GCS path: {prefix}/YYYY-MM-DD/R1C3/filename
        # This logic is specific to the runner, so we might need to adjust it.
        # For now, let's try to replicate the old logic.
        # The path in runner_chain is `data/snapshots/R1C1/snapshot_H30.json`
        # The desired GCS path is `prod/snapshots/R1C1/snapshot_H30.json`

        parts = local_file.parts
        if "data" in parts:
            # Find the index of 'data' and take everything after it
            data_index = parts.index("data")
            gcs_path_parts = parts[data_index + 1:]
        else:
            gcs_path_parts = parts

        gcs_path = f"{config.gcs_prefix}/{'/'.join(gcs_path_parts)}"

        blob = bucket.blob(gcs_path)
        blob.upload_from_filename(str(local_file))

        logger.debug(f"Uploaded {local_path} → gs://{config.gcs_bucket}/{gcs_path}")

    except Exception as e:
        logger.error(f"Failed to upload {local_path} to GCS: {e}", exc_info=e)

