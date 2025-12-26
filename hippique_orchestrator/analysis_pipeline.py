from __future__ import annotations
import logging
import traceback
from datetime import datetime, timezone
from typing import Any
import yaml
import json

from . import data_source, firestore_client, gcs_client, config
from .analysis_utils import (
    calculate_volatility,
    identify_outsider_reparable,
    identify_profil_oublie,
    parse_musique,
)
from .pipeline_run import generate_tickets
from .fetch_je_stats import collect_stats

logger = logging.getLogger(__name__)

async def run_analysis_for_phase(course_url: str, phase: str, date: str) -> dict[str, Any]:
    """
    Main entry point for processing a single course analysis triggered by a task.
    Orchestrates snapshot creation, enrichment, and ticket generation.
    """
    race_doc_id = firestore_client.get_doc_id_from_url(course_url, date)
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
        # --- Step 1: Scrape and save snapshot ---
        logger.info("Step 1: Fetching race details from data source.", extra=log_extra)
        snapshot_data = await data_source.fetch_race_details(course_url)
        if not snapshot_data or not snapshot_data.get("runners"):
            raise ValueError("Failed to fetch valid snapshot data or runners list is empty.")
        
        logger.info(
            "Snapshot fetched successfully.",
            extra={
                **log_extra,
                "race_name": snapshot_data.get("race_name"),
                "num_runners": len(snapshot_data.get("runners", [])),
            }
        )
        
        snapshot_id = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{phase}"
        gcs_path = f"data/{race_doc_id}/snapshots/{snapshot_id}.json"
        
        gcs_client.save_json_to_gcs(gcs_path, snapshot_data)
        logger.info(f"Step 1: Snapshot saved to GCS at {gcs_path}", extra=log_extra)

        # --- Step 2: Enrich snapshot and prepare for pipeline ---
        for runner in snapshot_data.get("runners", []):
            musique_str = runner.get("musique", "")
            parsed_musique_data = parse_musique(musique_str) if musique_str else {}
            runner["parsed_musique"] = parsed_musique_data
            runner["volatility"] = calculate_volatility(parsed_musique_data)
            runner["is_outsider_reparable"] = identify_outsider_reparable(runner)
            runner["is_profil_oublie"] = identify_profil_oublie(runner)

        analysis_content[f"snapshot_{phase.lower()}"] = {
            "gcs_path": gcs_path,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "id": snapshot_id
        }
        
        # --- Step 3: Run GPI ticket generation pipeline ---
        logger.info("Step 3: Preparing to run GPI ticket generation.", extra=log_extra)
        
        # Load GPI config and calibration from GCS
        gpi_config_content = gcs_client.read_file_from_gcs("config/gpi_v52.yml")
        gpi_config = yaml.safe_load(gpi_config_content) if gpi_config_content else {}

        calibration_content = gcs_client.read_file_from_gcs("config/payout_calibration.yaml")
        calibration_data = yaml.safe_load(calibration_content) if calibration_content else {}

        # Fetch stats
        stats_h5_path = collect_stats(h5=snapshot_data)
        stats_content = gcs_client.read_file_from_gcs(stats_h5_path)
        stats_data = json.loads(stats_content) if stats_content else {}

        # Prepare pipeline input
        gpi_config["budget"] = config.BUDGET_CAP_EUR
        gpi_config["calibration_data"] = calibration_data
        gpi_config["je_stats"] = stats_data
        gpi_config["h30_snapshot_data"] = {} # Placeholder for drift, to be implemented

        logger.info("Step 3: Calling generate_tickets.", extra=log_extra)
        tickets_analysis = generate_tickets(
            snapshot_data=snapshot_data,
            gpi_config=gpi_config,
        )

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
        analysis_content["status"] = "error"
        analysis_content["error_message"] = f"{type(e).__name__}: {e}"
        analysis_content["gpi_decision"] = "error_pipeline_failure"
        return analysis_content
