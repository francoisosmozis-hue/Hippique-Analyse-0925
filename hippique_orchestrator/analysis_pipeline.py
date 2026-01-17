from __future__ import annotations

import json
import logging
import re
import traceback
from datetime import datetime, timezone
from typing import Any

import yaml
from starlette.concurrency import run_in_threadpool

from . import firestore_client, gcs_client, stats_fetcher
from .source_registry import source_registry
from .analysis_utils import (
    calculate_volatility,
    identify_outsider_reparable,
    identify_profil_oublie,
    normalize_phase,
    parse_musique,
)
from .data_contract import Race, RaceSnapshot, Runner
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
    if calibration_content:
        yaml.safe_load(calibration_content)

    # Collect stats and merge into snapshot_data
    stats_gcs_path = await stats_fetcher.collect_stats(
        race_doc_id=race_doc_id,
        phase=phase,
        date=log_extra.get("date"),
        correlation_id=log_extra.get("correlation_id"),
        trace_id=log_extra.get("trace_id"),
    )

    collected_stats_content = gcs_client.read_file_from_gcs(stats_gcs_path)
    collected_stats = json.loads(collected_stats_content) if collected_stats_content else {}

    if collected_stats and collected_stats.get("rows"):
        stats_by_num = {str(s.get("num")): s for s in collected_stats["rows"]}
        for runner_data in snapshot_data.get("runners", []):
            runner_num = str(runner_data.get("num"))
            if runner_num in stats_by_num:
                runner_data["stats"] = stats_by_num[runner_num]
                # Merge individual stat fields into runner_data for direct access
                for k, v in stats_by_num[runner_num].items():
                    if k not in ["num", "name"]: # Avoid overwriting base runner info
                        runner_data[k] = v

    # Extract only the stats into je_stats dictionary for backward compatibility
    # Assuming runner_data in snapshot_data now has 'stats' key
    gpi_config["je_stats"] = {
        str(runner.get("num")): runner.get("stats", {})
        for runner in snapshot_data.get("runners", []) if runner.get("stats")
    }
    
    # Update snapshot_data with enriched runners is done in the loop above.

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
    race: Race, race_doc_id: str, phase: str, log_extra: dict
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetches race details via the source registry, parses, and saves the snapshot to GCS."""
    logger.info("Fetching race details from source registry.", extra=log_extra)
    
    try:
        provider = source_registry.get_primary_snapshot_provider()
        if not provider:
            logger.error("No primary snapshot provider is configured in the registry.", extra=log_extra)
            return None, None

        # Reconstruct identifiers for the provider
        meeting_id = f"R{race.reunion_id}"
        race_id_num = f"C{race.course_id}"
        
        # Run synchronous provider methods in a thread pool
        raw_snapshot = await run_in_threadpool(
            provider.fetch_snapshot,
            meeting_id=meeting_id,
            race_id=race_id_num,
            course_id=race_doc_id,
        )

        if not raw_snapshot:
            logger.warning("Provider returned no raw snapshot data.", extra=log_extra)
            return None, None

        snapshot_data = await run_in_threadpool(provider.parse_snapshot, raw_snapshot)

    except (NotImplementedError, Exception) as e:
        logger.error(f"Failed to fetch or parse snapshot from provider: {e}", exc_info=True, extra=log_extra)
        return None, None

    if not snapshot_data or not snapshot_data.get("runners"):
        logger.warning("Parsed snapshot data is empty or contains no runners.", extra=log_extra)
        return None, None

    logger.info(
        "Snapshot fetched and parsed successfully.",
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

    # --- Construct a Race object to pass to the provider ---
    try:
        match = re.match(r"(\d{4}-\d{2}-\d{2})_R(\d+)C(\d+)", race_doc_id)
        if not match:
            raise ValueError("race_doc_id format is invalid")
        
        race_date_str, reunion_id_str, course_id_str = match.groups()
        
        race_for_provider = Race(
            date=datetime.strptime(race_date_str, "%Y-%m-%d").date(),
            reunion_id=int(reunion_id_str),
            race_id=f"R{int(reunion_id_str)}C{int(course_id_str)}",
            course_id=int(course_id_str),
            url=course_url,
            # The following fields are not strictly necessary for get_race_details,
            # but are part of the contract.
            name=None,
            discipline=None,
            distance=None,
            corde=None,
            type_course=None,
            prize=None,
            start_time_local=None,
        )
    except (ValueError, TypeError) as e:
        logger.error(f"Failed to construct Race object from race_doc_id '{race_doc_id}': {e}", extra=log_extra)
        raise ValueError(f"Could not parse race_doc_id '{race_doc_id}'") from e
    # --- End Race object construction ---

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
            snapshot_data, gcs_path = await _fetch_and_save_snapshot(
                race_for_provider, race_doc_id, phase, log_extra
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
        snapshot_data, gcs_path = await _fetch_and_save_snapshot(
            race_for_provider, race_doc_id, phase, log_extra
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

        _enrich_snapshot(snapshot_data)

        tickets_analysis = await _run_gpi_pipeline(snapshot_data, gcs_path, race_doc_id, phase, log_extra)

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
