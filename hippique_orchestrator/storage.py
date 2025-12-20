"""
hippique_orchestrator/storage.py - Data Persistence Layer

Handles all interactions with Google Cloud Storage (GCS) and Firestore.
"""

import json
import logging
from pathlib import Path  # Added for local storage fallback
from typing import Any

import yaml

from . import firestore_client, gcs_client

logger = logging.getLogger(__name__)


def get_gpi_config(
    correlation_id: str | None = None, trace_id: str | None = None
) -> dict[str, Any]:
    """Loads the GPI YAML configuration from GCS or local filesystem."""
    gcs_manager = gcs_client.get_gcs_manager()

    config_filename = "config/gpi_v52.yml"
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}

    if gcs_manager:
        config_path = gcs_manager.get_gcs_path(config_filename)
        logger.info(f"Loading GPI config from GCS path {config_path}", extra=log_extra)
        with gcs_manager.fs.open(config_path, 'r') as f:
            return yaml.safe_load(f)
    else:
        # Fallback to local filesystem
        local_path = Path(config_filename)
        if not local_path.exists():
            raise FileNotFoundError(f"Local GPI config not found at {local_path}")
        logger.info(f"Loading GPI config from local path {local_path}", extra=log_extra)
        with open(local_path) as f:
            return yaml.safe_load(f)


def get_calibration_config(
    correlation_id: str | None = None, trace_id: str | None = None
) -> dict[str, Any]:
    """Loads the payout calibration YAML configuration from GCS or local filesystem."""
    gcs_manager = gcs_client.get_gcs_manager()

    config_filename = "config/payout_calibration.yaml"
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}

    if gcs_manager:
        config_path = gcs_manager.get_gcs_path(config_filename)
        logger.info(f"Loading calibration config from GCS path {config_path}", extra=log_extra)
        with gcs_manager.fs.open(config_path, 'r') as f:
            return yaml.safe_load(f)
    else:
        # Fallback to local filesystem
        local_path = Path(config_filename)
        if not local_path.exists():
            # This file is auto-created by pipeline_run.py if it doesn't exist.
            # For local dev, we might just return an empty dict if it's missing.
            logger.warning(
                f"Local calibration config not found at {local_path}. Returning empty config.",
                extra=log_extra,
            )
            return {}
        logger.info(f"Loading calibration config from local path {local_path}", extra=log_extra)
        with open(local_path) as f:
            return yaml.safe_load(f)


def save_snapshot(
    race_doc_id: str,
    phase: str,
    snapshot_id: str,
    data: dict[str, Any],
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> str:
    """
    Saves a race snapshot to GCS or local filesystem and returns the path.
    """
    gcs_manager = gcs_client.get_gcs_manager()

    gcs_path_str = f"data/{race_doc_id}/snapshots/{snapshot_id}.json"

    # Add correlation_id and trace_id to the stored data
    data_to_store = {**data, "correlation_id": correlation_id, "trace_id": trace_id}

    if gcs_manager:
        gcs_full_path = gcs_manager.get_gcs_path(gcs_path_str)
        log_extra = {
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "gcs_path": gcs_full_path,
        }
        logger.info("Saving snapshot to GCS", extra=log_extra)
        with gcs_manager.fs.open(gcs_full_path, 'w', encoding='utf-8') as f:
            json.dump(data_to_store, f, ensure_ascii=False, indent=2)
        return gcs_full_path
    else:
        # Fallback to local filesystem
        local_path = Path(gcs_path_str)  # Use the same path structure locally
        local_path.parent.mkdir(parents=True, exist_ok=True)
        log_extra = {
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "local_path": str(local_path),
        }
        logger.info("Saving snapshot to local filesystem", extra=log_extra)
        with open(local_path, 'w', encoding='utf-8') as f:
            json.dump(data_to_store, f, ensure_ascii=False, indent=2)
        return str(local_path)


def save_snapshot_metadata(
    race_doc_id: str,
    snapshot_id: str,
    metadata: dict[str, Any],
    correlation_id: str | None = None,
    trace_id: str | None = None,
):
    """Saves snapshot metadata to a Firestore subcollection."""
    collection_path = f"races/{race_doc_id}/snapshots"
    log_extra = {
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "firestore_path": f"{collection_path}/{snapshot_id}",
    }
    logger.info("Saving snapshot metadata to Firestore", extra=log_extra)
    # Ensure trace_id is in metadata
    metadata_to_save = {**metadata, "trace_id": trace_id}
    firestore_client.save_race_document(collection_path, snapshot_id, metadata_to_save)


def update_race_document(
    race_doc_id: str,
    data: dict[str, Any],
    correlation_id: str | None = None,
    trace_id: str | None = None,
):
    """Updates the main race document in Firestore."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "race_doc_id": race_doc_id}
    logger.info("Updating Firestore document", extra=log_extra)
    # Ensure trace_id is in the data to be updated
    data_to_update = {**data, "trace_id": trace_id}
    firestore_client.update_race_document("races", race_doc_id, data_to_update)


def get_race_document(
    race_doc_id: str, correlation_id: str | None = None, trace_id: str | None = None
) -> dict[str, Any] | None:
    """Retrieves a race document from Firestore."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "race_doc_id": race_doc_id}
    logger.info("Fetching Firestore document", extra=log_extra)
    return firestore_client.get_race_document("races", race_doc_id)


def get_latest_snapshot_metadata(
    race_doc_id: str, phase: str, correlation_id: str | None = None, trace_id: str | None = None
) -> dict[str, Any] | None:
    """Finds the metadata of the latest snapshot for a given phase in Firestore."""
    log_extra = {
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "race_doc_id": race_doc_id,
        "phase": phase,
    }
    logger.info("Looking for latest snapshot", extra=log_extra)
    snapshots = firestore_client.list_subcollection_documents("races", race_doc_id, "snapshots")
    candidates = [s for s in snapshots if s.get("phase") == phase]
    if not candidates:
        logger.warning(f"No '{phase}' snapshots found for {race_doc_id}", extra=log_extra)
        return None

    latest = sorted(candidates, key=lambda s: s.get("snapshot_id", ""))[-1]
    return latest


def load_snapshot_from_gcs(
    gcs_path: str, correlation_id: str | None = None, trace_id: str | None = None
) -> dict[str, Any]:
    """Loads and parses a JSON snapshot from a GCS path."""
    gcs_manager = gcs_client.get_gcs_manager()

    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "gcs_path": gcs_path}

    if gcs_manager:
        logger.info("Loading snapshot from GCS path", extra=log_extra)
        with gcs_manager.fs.open(gcs_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        # Fallback to local filesystem
        # gcs_path is actually the local path when USE_GCS is False, as returned by save_snapshot
        local_path = Path(gcs_path)
        if not local_path.exists():
            raise FileNotFoundError(f"Local snapshot not found at {local_path}")
        logger.info("Loading snapshot from local path", extra=log_extra)
        with open(local_path, encoding='utf-8') as f:
            return json.load(f)
