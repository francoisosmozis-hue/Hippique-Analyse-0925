"""Firestore client for saving and retrieving race data."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

from hippique_orchestrator import config
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

# Firestore client instance for lazy initialization
_db_client: firestore.Client | None = None


def _get_firestore_client() -> firestore.Client | None:
    global _db_client
    if _db_client:
        return _db_client

    if not config.PROJECT_ID:
        logger.warning(
            "FIRESTORE_PROJECT_ID is not configured. Firestore operations will be skipped (stateless mode)."
        )
        return None

    try:
        _db_client = firestore.Client(project=config.PROJECT_ID)
        logger.info(f"Firestore client initialized for project '{config.PROJECT_ID}'.")
        return _db_client
    except Exception as e:
        logger.error(
            f"Failed to initialize Firestore client for project '{config.PROJECT_ID}': {e}",
            exc_info=True,
        )
        # In case of initialization failure, prevent repeated attempts if it's a persistent config error
        # by keeping _db_client as None. Functions relying on it will then return None.
        return None


def get_document(collection: str, document_id: str) -> dict[str, Any] | None:
    """
    Retrieves a single document from a specified collection.
    """
    db_client = _get_firestore_client()
    if not db_client:
        logger.warning("Firestore is not available, cannot get document.")
        return None
    try:
        doc_ref = db_client.collection(collection).document(document_id)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"Failed to get document '{document_id}' from '{collection}': {e}", exc_info=e)
        return None


def set_document(collection: str, document_id: str, data: dict[str, Any]) -> None:
    """
    Sets (overwrites) a document in a specified collection.
    """
    db_client = _get_firestore_client()
    if not db_client:
        logger.warning("Firestore is not available, cannot set document.")
        return
    try:
        db_client.collection(collection).document(document_id).set(data)
        logger.debug(f"Document {document_id} set successfully in {collection}.")
    except Exception as e:
        logger.error(f"Failed to set document '{document_id}' in '{collection}': {e}", exc_info=e)


def update_race_document(document_id: str, data: dict[str, Any]) -> None:
    """Updates a document in the main races collection, merging data."""
    db_client = _get_firestore_client()
    if not db_client:
        logger.warning("Firestore is not available, skipping update.")
        return

    try:
        doc_ref = db_client.collection(config.FIRESTORE_COLLECTION).document(document_id)
        # Always set a last_modified_at timestamp for reliable ordering
        data["last_modified_at"] = datetime.now(timezone.utc).isoformat()
        logger.info(
            "Updating Firestore document",
            extra={
                "firestore_collection": config.FIRESTORE_COLLECTION,
                "document_id": document_id,
                "data_keys": list(data.keys()),
            },
        )
        doc_ref.set(data, merge=True)  # Use merge=True to be non-destructive
        logger.debug(f"Document {document_id} updated successfully.")
    except Exception as e:
        logger.error(f"Failed to update document {document_id}: {e}", exc_info=e)


async def get_races_for_date(date_str: str) -> list[firestore.DocumentSnapshot]:
    """Retrieves all race document snapshots for a given date."""
    db_client = _get_firestore_client()
    if not db_client:
        logger.warning("Firestore is not available, cannot query races.")
        return []

    try:
        races_ref = db_client.collection(config.FIRESTORE_COLLECTION)
        # Firestore __name__ queries require this format
        query = races_ref.order_by("__name__").start_at([date_str]).end_at([date_str + "\uf8ff"])

        logger.debug(
            "Executing Firestore query.",
            extra={"date_queried": date_str, "collection": config.FIRESTORE_COLLECTION, "query_start": date_str, "query_end": date_str + "\uf8ff"}
        )

        # Iterate through the stream explicitly to log yielded documents
        docs = []
        async for doc in query.stream():
            docs.append(doc)
            logger.debug(f"Document yielded from stream: {doc.id}")

        logger.debug(f"Firestore query stream finished. Collected {len(docs)} documents.")

        # Detailed logging for debugging API contradiction
        if not docs:
            logger.warning(
                "No documents found for date query.",
                extra={"date_queried": date_str, "collection": config.FIRESTORE_COLLECTION, "query_start": date_str, "query_end": date_str + "\uf8ff"}
            )
        else:
            logger.debug(
                "Documents found for date query.",
                extra={"date_queried": date_str, "num_docs_found": len(docs), "doc_ids": [d.id for d in docs]}
            )
        logger.info(
            "Queried races from Firestore",
            extra={"date_queried": date_str, "num_docs_found": len(docs)},
        )
        return docs
    except Exception as e:
        logger.error(f"Failed to query races by date {date_str}: {e}", exc_info=e)
        return []


def get_doc_id_from_url(url: str, date: str) -> str | None:
    """Extracts a race ID (e.g., R1C2) from a URL and prefixes it with the date."""
    rc_match = re.search(r"(?i)(?:^|[\/-])(r\d+c\d+)(?:[\/-]|$)", url)
    if not rc_match:
        return None
    rc_str = rc_match.group(1).upper()
    return f"{date}_{rc_str}"


async def get_processing_status_for_date(date_str: str, daily_plan: list[dict]) -> dict[str, Any]:
    """
    Aggregates processing status from Firestore and system config for the /ops/status endpoint.
    """
    db_client = _get_firestore_client()
    if not db_client:
        return {
            "error": "Firestore client is not available.",
            "reason_if_empty": "FIRESTORE_CONNECTION_FAILED",
        }

    races_from_db = await get_races_for_date(date_str)

    # Initialize counts
    counts = {
        "total_in_plan": len(daily_plan),
        "total_processed": len(races_from_db),
        "total_playable": 0,
        "total_abstain": 0,
        "total_error": 0,
        "total_pending": 0, # Will be calculated later
        "total_analyzed": 0,
    }

    # Process races from DB to update counts
    processed_race_ids = set()
    latest_processed_timestamp = None
    for doc in races_from_db:
        race_data = doc.to_dict()
        processed_race_ids.add(doc.id.split('_')[-1]) # Extract RC label
        counts["total_analyzed"] += 1

        analysis = race_data.get("tickets_analysis", {})
        decision = analysis.get("gpi_decision", "Pending").lower()

        if "play" in decision:
            counts["total_playable"] += 1
        elif "abstain" in decision:
            counts["total_abstain"] += 1
        elif "error" in decision:
            counts["total_error"] += 1
        
        # Track latest modification timestamp for processed races
        if last_mod_at := race_data.get("last_modified_at"):
            last_mod_dt = datetime.fromisoformat(last_mod_at)
            if latest_processed_timestamp is None or last_mod_dt > latest_processed_timestamp:
                latest_processed_timestamp = last_mod_dt

    # Calculate pending races
    plan_rc_labels = {f"{race['r_label']}{race['c_label']}" for race in daily_plan if 'r_label' in race and 'c_label' in race}
    counts["total_pending"] = len(plan_rc_labels - processed_race_ids)

    # --- Config Info ---
    config_info = {
        "project_id": config.PROJECT_ID,
        "firestore_collection": config.FIRESTORE_COLLECTION,
        "require_auth": config.REQUIRE_AUTH,
        "plan_source": "boturfers",  # Hardcoded for now
    }

    # --- Firestore Metadata ---
    firestore_meta = {
        "num_docs_today": len(races_from_db),
        "latest_processed_timestamp": latest_processed_timestamp.isoformat() if latest_processed_timestamp else None,
        "latest_global_doc_id": None, # Populate from global latest query
        "latest_global_timestamp": None, # Populate from global latest query
    }

    # Get latest global doc for metadata if no docs today
    if not races_from_db:
        latest_global_doc_query = (
            db_client.collection(config.FIRESTORE_COLLECTION)
            .order_by("last_modified_at", direction=firestore.Query.DESCENDING)
            .limit(1)
        )
        latest_global_docs = [doc for doc in latest_global_doc_query.stream()]
        if latest_global_docs and latest_global_docs[0].to_dict():
            latest_doc_data = latest_global_docs[0].to_dict()
            firestore_meta["latest_global_doc_id"] = latest_doc_data.get("race_doc_id")
            firestore_meta["latest_global_timestamp"] = latest_doc_data.get("last_modified_at")

    reason_if_empty = None
    if not daily_plan and not races_from_db:
        reason_if_empty = "NO_PLAN_AND_NO_FIRESTORE_DATA"
    elif not daily_plan:
        reason_if_empty = "NO_PLAN_FOR_DATE"
    elif not races_from_db:
        reason_if_empty = "NO_TASKS_PROCESSED_OR_FIRESTORE_EMPTY"
    
    return {
        "ok": True,
        "date": date_str,
        "status_message": f"Processed: {counts['total_processed']}, Playable: {counts['total_playable']}, Abstain: {counts['total_abstain']}, Errors: {counts['total_error']}, Pending: {counts['total_pending']}",
        "config": config_info,
        "counts": counts,
        "firestore_metadata": firestore_meta,
        "reason_if_empty": reason_if_empty,
        "last_task_attempt": firestore_meta["latest_processed_timestamp"],  # Use latest processed timestamp
        "last_error": None,  # Placeholder for actual error tracking
    }
