"""GCS utilities for uploading and downloading files."""

from __future__ import annotations

import os
from pathlib import Path

from google.cloud import storage

from hippique_orchestrator.config import get_config

logger = get_logger(__name__)

_gcs_client = None
config = get_config()

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
        # The path in runner_chain is typically `data/snapshots/R1C1/snapshot_H30.json`
        # or `data/analyses/R1C1/analysis.json`
        # The desired GCS path is `prod/snapshots/R1C1/snapshot_H30.json`
        # or `prod/analyses/R1C1/analysis.json`

        parts = local_file.parts
        # Find the index of 'data' or 'snapshots' or 'analyses'
        try:
            start_index = parts.index("data") + 1
        except ValueError:
            try:
                start_index = parts.index("snapshots")
            except ValueError:
                start_index = parts.index("analyses")
        gcs_path_parts = parts[start_index:]

        # Construct the GCS path using the configured prefix
        gcs_path = f"{config.gcs_prefix}/{'/'.join(gcs_path_parts)}"

        blob = bucket.blob(gcs_path)
        blob.upload_from_filename(str(local_file))

        logger.debug(f"Uploaded {local_path} → gs://{config.gcs_bucket}/{gcs_path}")

    except Exception as e:
        logger.error(f"Failed to upload {local_path} to GCS: {e}", exc_info=e)

