from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

import yaml

from . import config, data_source, firestore_client, gcs_client
from .analysis_utils import (
    calculate_volatility,
    identify_outsider_reparable,
    identify_profil_oublie,
    parse_musique,
)
from .fetch_je_stats import collect_stats
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

        # Filter for H-30 snapshots and get the most recent one
        h30_snapshots = sorted(
            [s for s in all_snapshots if "_H-30.json" in s],
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


def _run_gpi_pipeline(
    snapshot_data: dict[str, Any],
    snapshot_gcs_path: str,
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

    # Fetch stats
    stats_h5_path = collect_stats(h5=snapshot_gcs_path)
    stats_content = gcs_client.read_file_from_gcs(stats_h5_path)
    stats_data = json.loads(stats_content) if stats_content else {}

    # Prepare pipeline input
    gpi_config["budget"] = config.BUDGET_CAP_EUR
    gpi_config["calibration_data"] = calibration_data
    gpi_config["je_stats"] = stats_data

    # --- DRIFT LOGIC IMPLEMENTATION ---
    h30_snapshot_data = {}
    if phase == "H-5":
        logger.info("H-5 phase: attempting to load H-30 snapshot for drift.", extra=log_extra)
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
    snapshot_data = await data_source.fetch_race_details(course_url)
    if not snapshot_data or not snapshot_data.get("runners"):
        return None, None

    logger.info(
        "Snapshot fetched successfully.",
        extra={
            **log_extra,
            "race_name": snapshot_data.get("race_name"),
            "num_runners": len(snapshot_data.get("runners", [])),
        },
    )

    snapshot_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{phase}"
    gcs_path = f"data/{race_doc_id}/snapshots/{snapshot_id}.json"

    gcs_client.save_json_to_gcs(gcs_path, snapshot_data)
    logger.info(f"Snapshot saved to GCS at {gcs_path}", extra=log_extra)

    return snapshot_data, gcs_path


async def run_analysis_for_phase(
    course_url: str, phase: str, date: str, race_doc_id: str | None = None
) -> dict[str, Any]:
    """
    Main entry point for processing a single course analysis triggered by a task.
    Orchestrates snapshot creation, enrichment, and ticket generation.
    """
    race_doc_id = race_doc_id or firestore_client.get_doc_id_from_url(course_url, date)
    if not race_doc_id:
        raise ValueError(f"Could not determine race_doc_id from URL {course_url}")

    log_extra = {"race_doc_id": race_doc_id, "phase": phase, "date": date}
    logger.info("Starting analysis pipeline for phase.", extra=log_extra)

    analysis_content = {
        "last_analyzed_at": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "status": "processing",
    }

    try:
        snapshot_data, gcs_path = await _fetch_and_save_snapshot(
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

        _enrich_snapshot(snapshot_data)

        tickets_analysis = _run_gpi_pipeline(snapshot_data, gcs_path, race_doc_id, phase, log_extra)

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
                "error_message": f"{type(e).__name__}: {e}",
                "gpi_decision": "error_pipeline_failure",
            }
        )
        return analysis_content
