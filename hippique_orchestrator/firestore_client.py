"""Firestore client for saving and retrieving race data."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from google.cloud import firestore

from hippique_orchestrator import config
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

try:
    db = firestore.Client(project=config.PROJECT_ID)
    logger.info(f"Firestore client initialized for project '{config.PROJECT_ID}'.")
except Exception as e:
    db = None
    logger.error(f"Failed to initialize Firestore client: {e}", exc_info=True)


def update_race_document(document_id: str, data: dict[str, Any]) -> None:
    """Updates a document in the main races collection, merging data."""
    if not db:
        logger.warning("Firestore is not available, skipping update.")
        return

    try:
        doc_ref = db.collection(config.FIRESTORE_COLLECTION).document(document_id)
        logger.debug(f"Attempting to save document {document_id} in collection '{collection}'. Data keys: {list(data.keys())}.")
        doc_ref.set(data)
        logger.info(f"Document {document_id} updated successfully.")
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
        logger.info(f"Found {len(docs)} races in Firestore for date {date_str}.")
        return docs
    except Exception as e:
        logger.error(f"Failed to query races by date {date_str}: {e}", exc_info=e)
        return []


def get_doc_id_from_url(url: str, date: str) -> str | None:
    """Extracts a race ID (e.g., R1C2) from a URL and prefixes it with the date."""
    rc_match = re.search(r'-(r\dc\d+)-', url, re.IGNORECASE)
    if not rc_match:
        return None
    rc_str = rc_match.group(1).upper()
    return f"{date}_{rc_str}"


def get_processing_status_for_date(date_str: str, daily_plan: list[dict]) -> dict[str, Any]:
    """Aggregates processing status from Firestore for the /ops/status endpoint."""
    races_from_db = get_races_for_date(date_str)
    db_races_map = {doc.id.split('_')[-1]: doc.to_dict() for doc in races_from_db}

    race_statuses = []
    summary = {
        "total_in_plan": len(daily_plan),
        "total_processed": len(db_races_map),
        "playable": 0,
        "abstain": 0,
        "errors": 0,
    }

    for race in daily_plan:
        rc_label = race.get("c_label")
        if not rc_label or not race.get("r_label"):
            continue
        
        rc_key = f"{race.get('r_label')}{rc_label}"
        db_data = db_races_map.get(rc_key)
        
        status_entry = {
            "rc": rc_key,
            "name": race.get("name"),
            "time": race.get("time_local"),
            "firestore_status": "Not Processed",
            "last_analyzed_at": None,
            "error_reason": None,
        }

        if db_data:
            analysis = db_data.get("tickets_analysis", {})
            decision = analysis.get("gpi_decision", "Unknown")
            status_entry["firestore_status"] = decision
            status_entry["last_analyzed_at"] = db_data.get("last_analyzed_at")
            
            if "play" in decision.lower():
                summary["playable"] += 1
            elif "abstain" in decision.lower():
                summary["abstain"] += 1
            elif "error" in decision.lower():
                summary["errors"] += 1
                status_entry["error_reason"] = analysis.get("reason")

        race_statuses.append(status_entry)

    return {
        "date": date_str,
        "summary": summary,
        "races": race_statuses,
    }
