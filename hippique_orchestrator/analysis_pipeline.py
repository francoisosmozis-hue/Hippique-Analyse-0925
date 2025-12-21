from __future__ import annotations

import logging
import re
import traceback  # Add this import
from datetime import datetime, timezone
from typing import Any

from . import data_source, storage
from .pipeline_run import generate_tickets
from .stats_fetcher import collect_stats
from .analysis_utils import parse_musique, calculate_volatility, identify_outsider_reparable, identify_profil_oublie # New import

logger = logging.getLogger(__name__)


def get_race_doc_id(reunion: str, course: str, date: str | None = None) -> str:
    """Generates a unique Firestore document ID for a race for a specific date."""
    date_str = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{date_str}_{reunion}{course}"


def _find_race_url_in_programme(programme: dict, target_rc: str) -> str | None:
    """Finds the URL for a specific race in the scraped programme data."""
    if programme and programme.get("races"):
        for race in programme["races"]:
            if race.get("rc", "").replace(" ", "") == target_rc:
                return race.get("url")
    return None


def process_single_course_analysis(
    reunion: str,
    course: str,
    phase: str,
    date: str,
    budget: float,
    correlation_id: str | None = None,
    trace_id: str | None = None,
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
        "analysis_result": None,
        "correlation_id": correlation_id,
        "trace_id": trace_id,
    }
    log_extra = {
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "race_doc_id": race_doc_id,
    }

    try:
        # --- Step 1: Scrape race data ---
        logger.info(
            f"Step 1: Fetching {reunion}{course} from data source for phase {phase}",
            extra=log_extra,
        )
        programme_url = "https://www.boturfers.fr/programme-pmu-du-jour"  # Corrected typo in URL
        programme_data = data_source.fetch_programme(
            programme_url, correlation_id=correlation_id, trace_id=trace_id
        )

        target_rc = f"{reunion}{course}".replace(" ", "")
        race_url = _find_race_url_in_programme(programme_data, target_rc)

        if not race_url:
            result["message"] = f"Course {target_rc} not found in programme."
            logger.error(result["message"], extra=log_extra)
            return result
        logger.info(f"Step 1: Fetched race URL: {race_url}", extra=log_extra)

        snapshot_data = data_source.fetch_race_details(
            race_url, correlation_id=correlation_id, trace_id=trace_id
        )
        if not snapshot_data or "error" in snapshot_data:
            result["message"] = f"Failed to fetch race details for {race_url}"
            logger.error(result["message"], extra=log_extra)
            return result
        logger.info(f"Step 1: Fetched snapshot data for {race_doc_id}.", extra=log_extra)

        # Add parsed musique and volatility to runners
        for runner in snapshot_data.get("runners", []):
            musique_str = runner.get("musique", "")
            if musique_str:
                parsed_musique_data = parse_musique(musique_str)
                runner["parsed_musique"] = parsed_musique_data
                runner["volatility"] = calculate_volatility(parsed_musique_data)
            else:
                runner["parsed_musique"] = {}
                runner["volatility"] = "NEUTRE" # Default if no musique
            
            # Identify "outsider repérable"
            runner["is_outsider_reparable"] = identify_outsider_reparable(runner)
            
            # Identify "profil oublié"
            runner["is_profil_oublie"] = identify_profil_oublie(runner)

        logger.info(f"Step 1: Enriched snapshot data with musique, volatility, and outsider status for {race_doc_id}.", extra=log_extra)

        # --- Step 2: Persist initial snapshot ---
        logger.info(f"Step 2: Persisting initial snapshot for {race_doc_id}.", extra=log_extra)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snapshot_id = f"{timestamp}_{phase}"

        gcs_path = storage.save_snapshot(
            race_doc_id,
            phase,
            snapshot_id,
            snapshot_data,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        logger.info(f"Step 2: Snapshot saved to GCS: {gcs_path}", extra=log_extra)

        match = re.search(r"/(\d+)-", race_url)
        metadata = {
            "snapshot_id": snapshot_id,
            "gcs_snapshot_path": gcs_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "reunion": reunion,
            "course": course,
            "rc": target_rc,
            "id_course": match.group(1) if match else target_rc,
            "correlation_id": correlation_id,
            "trace_id": trace_id,
        }
        storage.save_snapshot_metadata(
            race_doc_id,
            snapshot_id,
            metadata,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        logger.info(
            f"Step 2: Snapshot metadata saved to Firestore for {race_doc_id}.",
            extra=log_extra,
        )

        # Update main doc with snapshot reference
        storage.update_race_document(
            race_doc_id,
            {f"{phase.lower()}_snapshot_ref": gcs_path},
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        logger.info(
            f"Step 2: Main race document updated with snapshot ref for {race_doc_id}.",
            extra=log_extra,
        )

        # --- Step 3: Enrichment and Pipeline (only for H5) ---
        if phase in ["H5", "H30"]:
            logger.info(
                (
                    "Step 3: Starting enrichment and ticket generation for"
                    f" {race_doc_id}, phase {phase}."
                ),
                extra=log_extra,
            )
            # 3a. Enrich with stats
            stats_gcs_path = collect_stats(
                race_doc_id=race_doc_id,
                phase=phase,
                date=date,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )

            # Since collect_stats is a placeholder, handle its dummy return value
            if stats_gcs_path == "dummy_gcs_path_for_stats":
                logger.warning(
                    "Using dummy stats as collect_stats is a placeholder.",
                    extra=log_extra,
                )
                stats_snapshot = {"coverage": 0, "rows": []}
            else:
                logger.info(
                    f"Loading stats snapshot from GCS: {stats_gcs_path}",
                    extra=log_extra,
                )
                stats_snapshot = storage.load_snapshot_from_gcs(
                    stats_gcs_path, correlation_id=correlation_id, trace_id=trace_id
                )

            coverage = stats_snapshot.get("coverage", 0)
            rows = stats_snapshot.get("rows", [])
            mapped_stats = {str(row.get("num")): row for row in rows}
            stats_payload = {"coverage": coverage, **mapped_stats}

            # 3b. Load H-30 data for Drift calculation if in H-5 phase
            h30_snapshot_data = None
            if phase == "H5":
                logger.info(
                    "H5 phase: trying to load H30 snapshot for drift analysis.",
                    extra=log_extra,
                )
                try:
                    h30_metadata = storage.get_latest_snapshot_metadata(
                        race_doc_id, "H30", correlation_id, trace_id
                    )
                    if h30_metadata and "gcs_snapshot_path" in h30_metadata:
                        h30_path = h30_metadata["gcs_snapshot_path"]
                        logger.info(f"Found H30 snapshot at {h30_path}", extra=log_extra)
                        h30_snapshot_data = storage.load_snapshot_from_gcs(
                            h30_path, correlation_id, trace_id
                        )
                    else:
                        logger.warning(
                            "H30 snapshot metadata not found for drift analysis.",
                            extra=log_extra,
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to load H30 snapshot: {e}",
                        exc_info=True,
                        extra=log_extra,
                    )

            # 3c. Generate tickets
            gpi_config = storage.get_gpi_config(correlation_id=correlation_id, trace_id=trace_id)
            calibration_data = storage.get_calibration_config(
                correlation_id=correlation_id, trace_id=trace_id
            )
            logger.info(
                f"Step 3: Calling generate_tickets for {race_doc_id}.",
                extra=log_extra,
            )
            gpi_config["budget"] = budget
            gpi_config["calibration_data"] = calibration_data
            gpi_config["je_stats"] = stats_payload
            gpi_config["h30_snapshot_data"] = h30_snapshot_data
            analysis_result = generate_tickets(
                snapshot_data=snapshot_data,
                gpi_config=gpi_config,
            )
            logger.info(
                (
                    "Step 3: generate_tickets returned:"
                    f" {analysis_result.get('gpi_decision')}. Tickets count:"
                    f" {len(analysis_result.get('tickets', []))}"
                ),
                extra=log_extra,
            )

            storage.update_race_document(
                race_doc_id,
                {
                    "tickets_analysis": analysis_result,
                    "last_analyzed_at": datetime.now(timezone.utc).isoformat(),
                    "correlation_id": correlation_id,
                    "trace_id": trace_id,
                },
                correlation_id=correlation_id,
                trace_id=trace_id,
            )
            logger.info(
                f"Step 3: Tickets analysis saved to Firestore for {race_doc_id}.",
                extra=log_extra,
            )

            result["analysis_result"] = analysis_result
            logger.info(
                (
                    f"Ticket generation complete for {race_doc_id}. Abstain:"
                    f" {analysis_result.get('abstain')}"
                ),
                extra=log_extra,
            )

        result["success"] = True
        result["message"] = "Processing complete."
        return result

    except Exception as e:
        full_traceback = traceback.format_exc()  # Capture full traceback
        logger.error(
            (
                "An unexpected error occurred in analysis pipeline for"
                f" {race_doc_id}: {e}\nTraceback: {full_traceback}"
            ),
            extra=log_extra,
        )
        result["message"] = f"An unexpected error occurred: {e}"
        result["full_traceback"] = full_traceback  # Add traceback to result for debugging
        return result
