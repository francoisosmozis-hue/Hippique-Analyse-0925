"""GCS utilities for uploading and downloading files."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from google.cloud import storage

from src.config.config import config
from hippique_orchestrator.logging_utils import get_logger

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
    return bool(config.gcs_bucket)

def disabled_reason() -> str | None:
    """Return a reason if GCS is disabled."""
    if not is_gcs_enabled():
        return "GCS_BUCKET_not_set"
    return None

def upload_file(local_path: str | os.PathLike[str], date: str) -> None:
    """
    Upload a single file to GCS, including the date in the path.
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

        # GCS path: {prefix}/{date}/{rc_name}/{filename}
        rc_name = local_file.parent.name  # e.g., R1C1
        filename = local_file.name

        gcs_path = f"{config.gcs_prefix}/{date}/{rc_name}/{filename}"

        blob = bucket.blob(gcs_path)
        blob.upload_from_filename(str(local_file))

        logger.debug(f"Uploaded {local_path} → gs://{config.gcs_bucket}/{gcs_path}")

    except Exception as e:
        logger.error(f"Failed to upload {local_path} to GCS: {e}", exc_info=e)


def upload_artifacts(rc_dir: Path, artifacts: list[str], date: str) -> None:
    """
    DEPRECATED: This function relies on local file artifacts. The new flow
    writes directly to GCS.
    Uploads a list of artifact files to GCS for a specific date.
    """
    if not is_gcs_enabled():
        return

    logger.warning("DEPRECATED: upload_artifacts is called. Should migrate to direct GCS writes.")
    logger.info(f"Uploading {len(artifacts)} artifacts to GCS from {rc_dir} for date {date}...")
    success_count = 0
    for artifact_path in artifacts:
        try:
            upload_file(artifact_path, date=date)
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to upload artifact {artifact_path}: {e}", exc_info=True)
    
    logger.info(f"Successfully uploaded {success_count}/{len(artifacts)} artifacts.")


def write_gcs_file(gcs_path: str, content: str | bytes, content_type: str | None = None) -> None:
    """
    Writes string or bytes content directly to a GCS file.
    """
    if not is_gcs_enabled():
        logger.debug("GCS is not enabled, skipping write.")
        return

    client = _get_gcs_client()
    if not client:
        logger.error("GCS client not available, cannot write file.")
        return

    try:
        bucket = client.bucket(config.gcs_bucket)
        # The gcs_path should be the full path within the bucket, e.g., "data/R1C1/file.json"
        blob = bucket.blob(gcs_path)
        
        if isinstance(content, str):
            blob.upload_from_string(content, content_type=content_type or 'text/plain')
        else:
            blob.upload_from_string(content, content_type=content_type or 'application/octet-stream')

        logger.debug(f"Written content to gs://{config.gcs_bucket}/{gcs_path}")

    except Exception as e:
        logger.error(f"Failed to write to GCS path {gcs_path}: {e}", exc_info=e)


def write_gcs_json(gcs_path: str, data: dict[str, Any]) -> None:
    """
    Serializes a dictionary to JSON and writes it directly to a GCS file.
    """
    try:
        json_content = json.dumps(data, ensure_ascii=False, indent=2)
        write_gcs_file(gcs_path, json_content, content_type='application/json')
    except TypeError as e:
        logger.error(f"Failed to serialize data for GCS path {gcs_path}: {e}", exc_info=True)



def get_pronostics_from_gcs(date: str) -> List[Dict[str, Any]]:
    """
    Fetches all analysis_H5.json files for a given date from GCS.
    """
    if not is_gcs_enabled():
        logger.warning("GCS is not enabled, cannot fetch pronostics.")
        return []

    client = _get_gcs_client()
    if not client:
        logger.error("GCS client not available.")
        return []

    bucket = client.bucket(config.gcs_bucket)
    # Prefix to search for all analyses for a given date
    prefix = f"{config.gcs_prefix}/{date}/"
    
    logger.info(f"Listing blobs in gs://{config.gcs_bucket}/{prefix} for files ending with 'analysis_H5.json'")
    
    all_pronostics = []
    for blob in list_gcs_files(prefix):
        if blob.name.endswith("analysis_H5.json"):
            logger.info(f"Found pronostic file: {blob.name}")
            try:
                content = blob.download_as_text()
                analysis_data = json.loads(content)
                all_pronostics.append(analysis_data)
            except json.JSONDecodeError:
                logger.warning(f"Malformed JSON in {blob.name}")
            except Exception as e:
                logger.error(f"Error reading {blob.name}: {e}")

    return all_pronostics


def read_gcs_json(gcs_path: str) -> dict[str, Any] | None:
    """
    Reads and parses a JSON file directly from GCS.
    """
    if not is_gcs_enabled():
        logger.debug("GCS is not enabled, cannot read file.")
        return None

    client = _get_gcs_client()
    if not client:
        logger.error("GCS client not available.")
        return None

    try:
        bucket = client.bucket(config.gcs_bucket)
        blob = bucket.blob(gcs_path)
        if not blob.exists():
            logger.warning(f"GCS file not found: gs://{config.gcs_bucket}/{gcs_path}")
            return None
        
        content = blob.download_as_text()
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning(f"Malformed JSON in gs://{config.gcs_bucket}/{gcs_path}")
        return None
    except Exception as e:
        logger.error(f"Error reading GCS file gs://{config.gcs_bucket}/{gcs_path}: {e}")
        return None


def list_gcs_files(prefix: str) -> list[storage.Blob]:
    """
    Lists all files in GCS matching a given prefix.
    """
    if not is_gcs_enabled():
        logger.warning("GCS is not enabled, cannot list files.")
        return []

    client = _get_gcs_client()
    if not client:
        logger.error("GCS client not available.")
        return []

    try:
        bucket = client.bucket(config.gcs_bucket)
        blobs = list(bucket.list_blobs(prefix=prefix))
        logger.debug(f"Found {len(blobs)} files in GCS with prefix '{prefix}'")
        return blobs
    except Exception as e:
        logger.error(f"Failed to list GCS files with prefix '{prefix}': {e}", exc_info=True)
        return []

