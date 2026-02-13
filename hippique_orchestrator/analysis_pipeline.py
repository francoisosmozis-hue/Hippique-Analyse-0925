from __future__ import annotations

import asyncio

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

import yaml

from . import config, firestore_client, gcs_client
from .analysis_utils import (
    calculate_volatility,
    identify_outsider_reparable,
    identify_profil_oublie,
    normalize_phase,
    parse_musique,
)
from .data_contract import RaceSnapshotNormalized
from .source_registry import source_registry
from .pipeline_run import generate_tickets

logger = logging.getLogger(__name__)


def _find_and_load_h30_snapshot(race_doc_id: str, log_extra: dict) -> dict[str, Any]:
    """Finds the latest H-30 snapshot for a given race and loads it."""
    snapshot_dir = f"data/{race_doc_id}/snapshots/"
    try:
        all_snapshots = gcs_client.list_files(snapshot_dir)
        if not all_snapshots:
            logger.warning(
                "No snapshots found in directory.", extra={**log_extra, "dir": snapshot_dir}
            )
            return {}

        # Flexible filtering for H-30 snapshots
        h30_snapshots = sorted(
            [s for s in all_snapshots if "_H-30.json" in s or "_H30.json" in s],
            reverse=True,
        )
        if not h30_snapshots:
            logger.warning("No H-30 snapshot found for drift calculation.", extra=log_extra)
            return {}

        latest_h30_path = h30_snapshots[0]
        logger.info(f"Found latest H-30 snapshot: {latest_h30_path}", extra=log_extra)

        h30_content = gcs_client.read_file_from_gcs(latest_h30_path)
        return json.loads(h30_content) if h30_content else {}

    except Exception as e:
        logger.error(f"Failed to find or load H-30 snapshot: {e}", extra=log_extra)
        return {}


async def _run_gpi_pipeline(
    snapshot_data: dict[str, Any],
    snapshot_gcs_path: str, # This parameter might become redundant if stats are not tied to a GCS path
    race_doc_id: str,
    phase: str,
    log_extra: dict,
) -> dict[str, Any]:
    """Loads configs and stats, then runs the GPI ticket generation pipeline."""
    logger.info("Preparing to run GPI ticket generation.", extra=log_extra)

    # Load GPI config and calibration from GCS
    gpi_config_content = gcs_client.read_file_from_gcs("config/gpi_v52.yml")
    gpi_config = yaml.safe_load(gpi_config_content) if gpi_config_content else {}

    calibration_content = gcs_client.read_file_from_gcs("config/payout_calibration.yaml")
    calibration_data = yaml.safe_load(calibration_content) if calibration_content else {}
    gpi_config["payout_calibration"] = calibration_data

    # Enrich the snapshot with stats using SourceRegistry
    # Assuming snapshot_data can be converted to RaceSnapshotNormalized for enrichment
    # Note: For simplicity, converting dict to RaceSnapshotNormalized here.
    # A more robust solution might involve proper data modeling upstream.
    snapshot_normalized = RaceSnapshotNormalized.model_validate(snapshot_data)

    enriched_snapshot = await source_registry.enrich_snapshot_with_stats(
        snapshot=snapshot_normalized,
        correlation_id=log_extra.get("correlation_id"),
        trace_id=log_extra.get("trace_id"),
    )

    # Convert back to dict for pipeline processing
    # Extract only the stats into je_stats dictionary for backward compatibility
    gpi_config["je_stats"] = {
        runner.name: runner.stats.model_dump()
        for runner in enriched_snapshot.runners if runner.stats
    }
    # Update snapshot_data with enriched runners
    snapshot_data["runners"] = [runner.model_dump() for runner in enriched_snapshot.runners]

    # --- DRIFT LOGIC IMPLEMENTATION ---
    h30_snapshot_data = {}
    if phase == "H5":
        logger.info("H5 phase: attempting to load H30 snapshot for drift.", extra=log_extra)
        h30_snapshot_data = _find_and_load_h30_snapshot(race_doc_id, log_extra)
    gpi_config["h30_snapshot_data"] = h30_snapshot_data
    # --- END DRIFT LOGIC ---

    logger.info("Calling generate_tickets.", extra=log_extra)
    tickets_analysis = generate_tickets(
        snapshot_data=snapshot_data,
        gpi_config=gpi_config,
    )
    return tickets_analysis


def _enrich_snapshot(snapshot_data: dict[str, Any]):
    """Enriches snapshot data with musique parsing, volatility, and profiles."""
    for runner in snapshot_data.get("runners", []):
        musique_str = runner.get("musique", "")
        parsed_musique_data = parse_musique(musique_str) if musique_str else {}
        runner["parsed_musique"] = parsed_musique_data
        runner["volatility"] = calculate_volatility(parsed_musique_data)
        runner["is_outsider_reparable"] = identify_outsider_reparable(runner)
        runner["is_profil_oublie"] = identify_profil_oublie(runner)


async def _fetch_and_save_snapshot(
    course_url: str, race_doc_id: str, phase: str, log_extra: dict
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetches race details and saves the snapshot to GCS."""
    logger.info("Fetching race details from data source.", extra=log_extra)
    snapshot_data = await source_registry.get_snapshot(course_url, date=log_extra["date"], phase=phase, correlation_id=log_extra["correlation_id"], trace_id=log_extra["trace_id"])
    if not snapshot_data or not snapshot_data.get("runners"):
        return None, None

    logger.info(
        "Snapshot fetched successfully.",
        extra={
            **log_extra,
            "race_name": snapshot_data.race.nom, # Access race.nom from RaceSnapshotNormalized
            "num_runners": len(snapshot_data.runners), # Access runners from RaceSnapshotNormalized
        },
    )

    snapshot_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{phase}"
    gcs_path = f"data/{race_doc_id}/snapshots/{snapshot_id}.json"

    gcs_client.save_json_to_gcs(gcs_path, snapshot_data.model_dump_json()) # Save Pydantic model as JSON string
    logger.info(f"Snapshot saved to GCS at {gcs_path}", extra=log_extra)

    return snapshot_data.model_dump(), gcs_path # Return dict version of snapshot_data


async def run_analysis_for_phase(
    course_url: str,
    phase: str,
    date: str,
    race_doc_id: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    """
    Main entry point for processing a single course analysis triggered by a task.
    Orchestrates snapshot creation, enrichment, and ticket generation.
    """
    phase = normalize_phase(phase)
    race_doc_id = race_doc_id or firestore_client.get_doc_id_from_url(course_url, date)
    if not race_doc_id:
        raise ValueError(f"Could not determine race_doc_id from URL {course_url}")

    log_extra = {
        "race_doc_id": race_doc_id,
        "phase": phase,
        "date": date,
        "correlation_id": correlation_id,
        "trace_id": trace_id,
    }
    logger.info("Starting analysis pipeline for phase.", extra=log_extra)

    analysis_content = {
        "ok": True,  # analysis completed (even if abstention); set to False only on error
        "race_doc_id": race_doc_id,
        "last_analyzed_at": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "status": "processing",
    }

    try:
        # H9 phase is snapshot-only
        if phase == "H9":
            snapshot_data_dict, gcs_path = await _fetch_and_save_snapshot(
                course_url, race_doc_id, phase, log_extra
            )
            analysis_content.update(
                {
                    "status": "snapshot_only",
                    "ok": True,
                    "gpi_decision": "SNAPSHOT_ONLY_H9",
                    "gcs_path": gcs_path, # Include GCS path of the saved snapshot
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "abstention_raisons": ["H9 phase is for snapshot only, no GPI analysis."],
                }
            )
            logger.info(f"H9 snapshot for {race_doc_id} created successfully.", extra=log_extra)
            return analysis_content

        # For H5 and H30 phases, continue with full analysis
        snapshot_data_dict, gcs_path = await _fetch_and_save_snapshot(
            course_url, race_doc_id, phase, log_extra
        )
        if not snapshot_data:
            reason = "NO_DATA: snapshot missing or runners empty"
            logger.warning(
                "Snapshot invalid or runners empty -> abstention.",
                extra={**log_extra, "reason": reason},
            )
            analysis_content.update(
                {
                    "status": "abstention",
                    "ok": True,
                    "gpi_decision": "ABSTENTION_NO_DATA",
                    "abstention_raisons": [reason],
                    "tickets_analysis": {
                        "gpi_decision": "ABSTENTION_NO_DATA",
                        "final_tickets": [],
                        "total_ev_gpi": None,
                        "total_mise": 0,
                        "abstention_raisons": [reason],
                    },
                }
            )
            return analysis_content

        analysis_content[f"snapshot_{phase.lower()}"] = {
            "gcs_path": gcs_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        _enrich_snapshot(snapshot_data_dict)

        tickets_analysis = await _run_gpi_pipeline(snapshot_data_dict, gcs_path, race_doc_id, phase, log_extra)

        analysis_content["tickets_analysis"] = tickets_analysis
        gpi_decision = tickets_analysis.get("gpi_decision", "error_in_analysis")
        analysis_content["gpi_decision"] = gpi_decision
        analysis_content["status"] = "analyzed"

        logger.info(
            "Analysis and ticket generation complete.",
            extra={
                **log_extra,
                "gpi_decision": gpi_decision,
                "num_tickets": len(tickets_analysis.get("final_tickets", [])),
                "total_ev_gpi": tickets_analysis.get("total_ev_gpi"),
                "total_mise": tickets_analysis.get("total_mise"),
                "abstention_raisons": tickets_analysis.get("abstention_raisons", []),
            },
        )

        return analysis_content

    except Exception as e:
        tb_str = traceback.format_exc()
        logger.error(f"Analysis pipeline failed: {e}\n{tb_str}", extra=log_extra)
        analysis_content.update(
            {
                "status": "error",
                "ok": False,
                "error_message": f"{type(e).__name__}: {e}",
                "gpi_decision": "error_pipeline_failure",
            }
        )
        return analysis_content
