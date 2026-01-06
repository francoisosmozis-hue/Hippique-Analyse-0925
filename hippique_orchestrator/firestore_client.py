"""Firestore client for saving and retrieving race data."""

from __future__ import annotations

import re
from typing import Any

from google.cloud import firestore

from hippique_orchestrator import config
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

# Initialize the Firestore client globally.
# Let it raise an exception if configuration (e.g., project ID, credentials) is wrong.
# The application should fail to start if it cannot connect to the database.
db = firestore.Client(project=config.PROJECT_ID)
logger.info(f"Firestore client initialized for project '{config.PROJECT_ID}'.")


def get_document(collection: str, document_id: str) -> dict[str, Any] | None:
    """
    Retrieves a single document from a specified collection.
    """
    if not db:
        logger.warning("Firestore is not available, cannot get document.")
        return None
    try:
        doc_ref = db.collection(collection).document(document_id)
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
    if not db:
        logger.warning("Firestore is not available, cannot set document.")
        return
    try:
        db.collection(collection).document(document_id).set(data)
        logger.debug(f"Document {document_id} set successfully in {collection}.")
    except Exception as e:
        logger.error(f"Failed to set document '{document_id}' in '{collection}': {e}", exc_info=e)


def update_race_document(document_id: str, data: dict[str, Any]) -> None:
    """Updates a document in the main races collection, merging data."""
    if not db:
        logger.warning("Firestore is not available, skipping update.")
        return

    try:
        doc_ref = db.collection(config.FIRESTORE_COLLECTION).document(document_id)
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


def get_races_for_date(date_str: str) -> list[firestore.DocumentSnapshot]:
    """Retrieves all race document snapshots for a given date."""
    if not db:
        logger.warning("Firestore is not available, cannot query races.")
        return []

    try:
        races_ref = db.collection(config.FIRESTORE_COLLECTION)
        # Firestore __name__ queries require this format
        query = races_ref.order_by("__name__").start_at([date_str]).end_at([date_str + "\uf8ff"])
        docs = list(query.stream())
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


def get_processing_status_for_date(date_str: str, daily_plan: list[dict]) -> dict[str, Any]:
    """
    Aggregates processing status from Firestore and system config for the /ops/status endpoint.
    """
    if not db:
        return {
            "error": "Firestore client is not available.",
            "reason_if_empty": "FIRESTORE_CONNECTION_FAILED",
        }

    races_from_db = get_races_for_date(date_str)
    db_races_map = {doc.id.split('_')[-1]: doc.to_dict() for doc in races_from_db}

    # --- Config Info ---
    config_info = {
        "project_id": config.PROJECT_ID,
        "firestore_collection": config.FIRESTORE_COLLECTION,
        "require_auth": config.REQUIRE_AUTH,
        "plan_source": "boturfers",  # Hardcoded for now
    }

    # --- Firestore Metadata ---
    docs_count = len(races_from_db)
    last_update_ts = None
    if races_from_db:
        last_doc = max(races_from_db, key=lambda doc: doc.update_time)
        last_doc_id = last_doc.id
        last_update_ts = last_doc.update_time.isoformat()
    else:
        # If no docs for today, check for the latest doc in the entire collection
        # to differentiate between a stalled and an empty system.
        latest_doc_query = (
            db.collection(config.FIRESTORE_COLLECTION)
            .order_by("update_time", direction=firestore.Query.DESCENDING)
            .limit(1)
        )
        latest_docs = list(latest_doc_query.stream())
        if latest_docs:
            last_doc_id = latest_docs[0].id
            last_update_ts = latest_docs[0].update_time.isoformat()
        else:
            last_doc_id = None

    firestore_meta = {
        "docs_count_for_date": docs_count,
        "last_doc_id": last_doc_id,
        "last_update_ts": last_update_ts,
    }

    # --- Counts & Status ---
    counts = {
        "total_in_plan": len(daily_plan),
        "total_processed": len(db_races_map),
        "total_playable": 0,
        "total_abstain": 0,
        "total_error": 0,
    }
    counts["total_pending"] = counts["total_in_plan"] - counts["total_processed"]

    for _rc_key, db_data in db_races_map.items():
        decision = db_data.get("tickets_analysis", {}).get("gpi_decision", "Unknown").lower()
        if "play" in decision:
            counts["total_playable"] += 1
        elif "abstain" in decision:
            counts["total_abstain"] += 1
        elif "error" in decision:
            counts["total_error"] += 1

    # --- Determine Reason if Empty ---
    reason_if_empty = None
    if counts["total_in_plan"] > 0 and counts["total_processed"] == 0:
        # This is the key state to diagnose. More reasons can be added.
        if not firestore_meta["last_update_ts"]:
            reason_if_empty = "NO_TASKS_PROCESSED_OR_FIRESTORE_EMPTY"
        else:
            reason_if_empty = "PROCESSING_STALLED"
    elif counts["total_in_plan"] == 0:
        reason_if_empty = "PLAN_SCRAPING_FAILED_OR_NO_RACES_TODAY"

    return {
        "date": date_str,
        "config": config_info,
        "counts": counts,
        "firestore_metadata": firestore_meta,
        "reason_if_empty": reason_if_empty,
        "last_task_attempt": None,  # Placeholder
        "last_error": None,  # Placeholder
    }
