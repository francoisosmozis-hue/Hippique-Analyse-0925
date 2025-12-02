"""
hippique_orchestrator/storage.py - Data Persistence Layer

Handles all interactions with Google Cloud Storage (GCS) and Firestore.
"""

import json
import logging
from typing import Any, Dict

import yaml

from . import firestore_client, gcs_client

logger = logging.getLogger(__name__)


def get_gpi_config(correlation_id: str | None = None, trace_id: str | None = None) -> Dict[str, Any]:
    """Loads the GPI YAML configuration from GCS."""
    gcs_manager = gcs_client.get_gcs_manager()
    if not gcs_manager:
        raise RuntimeError("GCS Manager is not initialized.")
        
    config_path = gcs_manager.get_gcs_path("config/gpi_v52.yml")
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}
    logger.info(f"Loading GPI config from {config_path}", extra=log_extra)
    with gcs_manager.fs.open(config_path, 'r') as f:
        return yaml.safe_load(f)


def get_calibration_config(correlation_id: str | None = None, trace_id: str | None = None) -> Dict[str, Any]:
    """Loads the payout calibration YAML configuration from GCS."""
    gcs_manager = gcs_client.get_gcs_manager()
    if not gcs_manager:
        raise RuntimeError("GCS Manager is not initialized.")

    config_path = gcs_manager.get_gcs_path("config/payout_calibration.yaml")
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id}
    logger.info(f"Loading calibration config from {config_path}", extra=log_extra)
    with gcs_manager.fs.open(config_path, 'r') as f:
        return yaml.safe_load(f)


def save_snapshot(race_doc_id: str, phase: str, snapshot_id: str, data: Dict[str, Any], correlation_id: str | None = None, trace_id: str | None = None) -> str:
    """
    Saves a race snapshot to GCS and returns the GCS path.
    """
    gcs_manager = gcs_client.get_gcs_manager()
    if not gcs_manager:
        raise RuntimeError("GCS Manager is not initialized.")

    gcs_path_str = f"data/{race_doc_id}/snapshots/{snapshot_id}.json"
    gcs_full_path = gcs_manager.get_gcs_path(gcs_path_str)
    
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "gcs_path": gcs_full_path}
    logger.info("Saving snapshot to GCS", extra=log_extra)
    
    # Add correlation_id and trace_id to the stored data
    data_to_store = {**data, "correlation_id": correlation_id, "trace_id": trace_id}
    
    with gcs_manager.fs.open(gcs_full_path, 'w', encoding='utf-8') as f:
        json.dump(data_to_store, f, ensure_ascii=False, indent=2)
        
    return gcs_full_path


def save_snapshot_metadata(race_doc_id: str, snapshot_id: str, metadata: Dict[str, Any], correlation_id: str | None = None, trace_id: str | None = None):
    """Saves snapshot metadata to a Firestore subcollection."""
    collection_path = f"races/{race_doc_id}/snapshots"
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "firestore_path": f"{collection_path}/{snapshot_id}"}
    logger.info("Saving snapshot metadata to Firestore", extra=log_extra)
    # Ensure trace_id is in metadata
    metadata_to_save = {**metadata, "trace_id": trace_id}
    firestore_client.save_race_document(collection_path, snapshot_id, metadata_to_save)


def update_race_document(race_doc_id: str, data: Dict[str, Any], correlation_id: str | None = None, trace_id: str | None = None):
    """Updates the main race document in Firestore."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "race_doc_id": race_doc_id}
    logger.info("Updating Firestore document", extra=log_extra)
    # Ensure trace_id is in the data to be updated
    data_to_update = {**data, "trace_id": trace_id}
    firestore_client.update_race_document("races", race_doc_id, data_to_update)


def get_race_document(race_doc_id: str, correlation_id: str | None = None, trace_id: str | None = None) -> Dict[str, Any] | None:
    """Retrieves a race document from Firestore."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "race_doc_id": race_doc_id}
    logger.info("Fetching Firestore document", extra=log_extra)
    return firestore_client.get_race_document("races", race_doc_id)


def get_latest_snapshot_metadata(race_doc_id: str, phase: str, correlation_id: str | None = None, trace_id: str | None = None) -> Dict[str, Any] | None:
    """Finds the metadata of the latest snapshot for a given phase in Firestore."""
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "race_doc_id": race_doc_id, "phase": phase}
    logger.info("Looking for latest snapshot", extra=log_extra)
    snapshots = firestore_client.list_subcollection_documents("races", race_doc_id, "snapshots")
    candidates = [s for s in snapshots if s.get("phase") == phase]
    if not candidates:
        logger.warning(f"No '{phase}' snapshots found for {race_doc_id}", extra=log_extra)
        return None
    
    latest = sorted(candidates, key=lambda s: s.get("snapshot_id", ""))[-1]
    return latest


def load_snapshot_from_gcs(gcs_path: str, correlation_id: str | None = None, trace_id: str | None = None) -> Dict[str, Any]:
    """Loads and parses a JSON snapshot from a GCS path."""
    gcs_manager = gcs_client.get_gcs_manager()
    if not gcs_manager:
        raise RuntimeError("GCS Manager is not initialized.")
        
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "gcs_path": gcs_path}
    logger.info("Loading snapshot from GCS path", extra=log_extra)
    with gcs_manager.fs.open(gcs_path, 'r', encoding='utf-8') as f:
        return json.load(f)