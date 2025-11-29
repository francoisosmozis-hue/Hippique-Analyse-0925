#!/usr/bin/env python3
"""
Firestore-native pipeline for analysing today's horse races.
This module orchestrates the fetching, enrichment, and analysis of race data,
persisting all state and artifacts to Firestore.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hippique_orchestrator.stats_fetcher import collect_stats
# Refactored pipeline_run to import the pure ticket generation logic
from hippique_orchestrator.pipeline_run import generate_tickets, load_gpi_config

# Assuming firestore_client is correctly configured and available.
from hippique_orchestrator import firestore_client
# Assuming the scraper is available
try:
    from .online_fetch_boturfers import fetch_boturfers_programme, fetch_boturfers_race_details
except ImportError:
    def fetch_boturfers_programme(*args, **kwargs):
        raise RuntimeError("Boturfers programme fetcher is unavailable")
    def fetch_boturfers_race_details(*args, **kwargs):
        raise RuntimeError("Boturfers race details fetcher is unavailable")

logger = logging.getLogger(__name__)

# --- Primary Business Logic ---

def get_race_doc_id(reunion: str, course: str, date: str | None = None) -> str:
    """Generates a unique Firestore document ID for a race for a specific date."""
    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{date_str}_{reunion}{course}"


def create_snapshot(reunion: str, course: str, phase: str, race_doc_id: str) -> bool:
    """
    Fetches race details from Boturfers and writes a snapshot to Firestore.
    Returns True on success, False on failure.
    """
    logger.info(f"Fetching {reunion}{course} from Boturfers for phase {phase}")
    try:
        # This could be cached for a short period to avoid re-fetching for every race
        programme_url = "https://www.boturfers.fr/programme-pmu-du-jour"
        programme_data = fetch_boturfers_programme(programme_url)

        race_url = None
        target_rc = f"{reunion}{course}".replace(" ", "")
        if programme_data and programme_data.get("races"):
            for race in programme_data["races"]:
                if race.get("rc", "").replace(" ", "") == target_rc:
                    race_url = race.get("url")
                    break

        if not race_url:
            logger.error(f"Course {target_rc} not found in Boturfers programme.")
            return False

        race_details = fetch_boturfers_race_details(race_url)
        if not race_details or "error" in race_details:
            logger.error(f"Failed to fetch race details for {race_url}")
            return False

        # Add metadata
        race_details['reunion'] = reunion
        race_details['course'] = course
        race_details['rc'] = target_rc
        match = re.search(r'/(\d+)-', race_url)
        race_details['id_course'] = match.group(1) if match else target_rc

        # Save snapshot to a subcollection in Firestore
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snapshot_id = f"{timestamp}_{phase}"
        
        # Also add the snapshot_id to the document data itself for filtering
        race_details['snapshot_id'] = snapshot_id

        firestore_client.save_race_document(
            f"races/{race_doc_id}/snapshots", snapshot_id, race_details
        )
        logger.info(f"Snapshot for {target_rc} saved to Firestore: races/{race_doc_id}/snapshots/{snapshot_id}")
        return True
    except Exception as e:
        logger.exception(f"Exception during snapshot creation for {reunion}{course}: {e}")
        return False


def enrich_h5_with_stats(race_doc_id: str) -> bool:
    """
    Enriches the H5 data with H30 comparison and J/E stats, writing back to Firestore.
    Returns True on success, False on failure.
    """
    logger.info(f"Enriching H5 for {race_doc_id}")

    def _get_latest_snapshot(tag: str) -> dict[str, Any] | None:
        """Find the latest snapshot for a given tag in Firestore."""
        snapshots = firestore_client.list_subcollection_documents("races", race_doc_id, "snapshots")
        candidates = [s for s in snapshots if f"_{tag}" in s.get("snapshot_id", "")]
        if not candidates:
            return None
        return sorted(candidates, key=lambda s: s.get("snapshot_id", ""))[-1]

    h5_payload = _get_latest_snapshot("H5")
    if not h5_payload:
        logger.error(f"H5 snapshot missing for {race_doc_id}")
        return False

    h30_payload = _get_latest_snapshot("H30")
    if not h30_payload:
        logger.warning(f"H30 snapshot missing for {race_doc_id}. Proceeding without H30 data.")

    # --- Prepare stats fetching ---
    course_id = str(h5_payload.get("id_course") or "").strip()
    if not course_id:
        logger.error(f"Could not determine course_id for {race_doc_id}")
        return False

    stats_payload = {"coverage": 0, "ok": 0}
    # Workaround for collect_stats requiring a local file
    with tempfile.NamedTemporaryFile(mode='w+', delete=True, suffix=".json", prefix=f"{race_doc_id}_") as tmp_h5_file:
        json.dump(h5_payload, tmp_h5_file)
        tmp_h5_file.flush() # Ensure data is written to disk

        try:
            stats_json_path_str = collect_stats(h5=tmp_h5_file.name, out=f"{tmp_h5_file.name}.csv")
            stats_json_path = Path(stats_json_path_str)
            if stats_json_path.exists():
                stats_result = json.loads(stats_json_path.read_text(encoding="utf-8"))
                coverage = stats_result.get("coverage", 0)
                rows = stats_result.get("rows", [])
                mapped = {str(row.get("num")): row for row in rows}
                stats_payload = {"coverage": coverage, **mapped}
                stats_json_path.unlink(missing_ok=True) # Clean up stats file
            else:
                 logger.warning(f"collect_stats did not produce the expected file: {stats_json_path_str}")

        except Exception:
            logger.exception("collect_stats failed for course %s", course_id)

    # --- Update Firestore document ---
    update_payload = {
        "h5_snapshot": h5_payload,
        "h30_snapshot": h30_payload or {},
        "stats_je": stats_payload,
        "last_enriched_at": datetime.now(timezone.utc).isoformat()
    }
    
    try:
        firestore_client.update_race_document("races", race_doc_id, update_payload)
        logger.info(f"Enrichment data for {race_doc_id} saved to Firestore.")
        return True
    except Exception as e:
        logger.exception(f"Failed to update Firestore document for {race_doc_id}: {e}")
        return False

def run_ticket_generation_pipeline(race_doc_id: str, budget: float) -> dict[str, Any] | None:
    """
    Runs the ticket generation pipeline using data from Firestore.
    """
    logger.info(f"Running ticket generation for {race_doc_id}")
    
    race_doc = firestore_client.get_race_document("races", race_doc_id)
    if not race_doc:
        logger.error(f"Race document not found in Firestore for {race_doc_id}")
        return None

    h5_snapshot = race_doc.get("h5_snapshot")
    if not h5_snapshot or not h5_snapshot.get("runners"):
        logger.error(f"H5 snapshot with runners is missing for {race_doc_id}")
        return None

    # Load GPI config (assuming it's at a standard path)
    try:
        gpi_config_path = Path(__file__).resolve().parent / "config" / "gpi_v52.yml"
        gpi_config = load_gpi_config(gpi_config_path)
    except Exception:
        logger.exception("Failed to load GPI config.")
        return None

    # Load calibration path (assuming standard path)
    calibration_path = str(Path(__file__).resolve().parent / "config" / "payout_calibration.yaml")

    # Execute the pure ticket generation logic
    ticket_results = generate_tickets(
        snapshot_data=h5_snapshot,
        gpi_config=gpi_config,
        budget=budget,
        calibration_path=calibration_path,
        allow_heuristic=False
    )
    
    # Update Firestore with the results
    update_payload = {
        "tickets_analysis": ticket_results,
        "last_analyzed_at": datetime.now(timezone.utc).isoformat()
    }
    firestore_client.update_race_document("races", race_doc_id, update_payload)
    
    logger.info(f"Ticket generation complete for {race_doc_id}. Abstain: {ticket_results.get('abstain')}")
    return ticket_results


def process_single_course_analysis(
    reunion: str,
    course: str,
    phase: str,
    date: str,
    budget: float,
) -> dict[str, Any]:
    """
    Main entry point for processing a single course.
    Orchestrates snapshot creation, enrichment, and ticket generation.
    """
    race_doc_id = get_race_doc_id(reunion, course, date)
    result = {
        "race_doc_id": race_doc_id,
        "phase": phase,
        "success": False,
        "message": "",
        "analysis_result": None
    }

    # --- Step 1: Create Snapshot ---
    if not create_snapshot(reunion, course, phase, race_doc_id):
        result["message"] = "Failed to create snapshot from Boturfers."
        return result

    # --- Step 2: Enrichment and Pipeline (only for H5) ---
    if phase == "H5":
        if not enrich_h5_with_stats(race_doc_id):
            result["message"] = "Failed to enrich H5 data with stats."
            return result
        
        analysis_result = run_ticket_generation_pipeline(race_doc_id, budget)
        if analysis_result is None:
            result["message"] = "Ticket generation pipeline failed to run."
            return result
        
        result["analysis_result"] = analysis_result

    result["success"] = True
    result["message"] = "Processing complete."
    return result
