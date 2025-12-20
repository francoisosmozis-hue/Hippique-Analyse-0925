"""
Fetches and aggregates statistics for a given race, including chrono data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import storage, zoneturf_client

LOGGER = logging.getLogger(__name__)


def collect_stats(
    race_doc_id: str,
    phase: str,
    date: str,  # Keep for potential future use
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> str:
    """
    Orchestrates the collection of all stats for the runners in a race.
    Currently fetches chrono stats from Zone-Turf.
    Saves the aggregated stats to GCS and returns the path.
    """
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "race_doc_id": race_doc_id}
    LOGGER.info(f"Starting stats collection for {race_doc_id}", extra=log_extra)

    # 1. Get the list of runners from the main race document
    # We need the snapshot data, not the race doc itself, to get runner names.
    # Let's get the latest snapshot metadata for the current phase.
    latest_snapshot_meta = storage.get_latest_snapshot_metadata(
        race_doc_id, phase, correlation_id, trace_id
    )
    if not (latest_snapshot_meta and latest_snapshot_meta.get("gcs_snapshot_path")):
        LOGGER.error(
            f"Cannot collect stats, no snapshot found for {race_doc_id} in phase {phase}",
            extra=log_extra,
        )
        # Return the placeholder value to avoid breaking the pipeline, but log error.
        return "dummy_gcs_path_for_stats"

    snapshot_path = latest_snapshot_meta["gcs_snapshot_path"]
    snapshot_data = storage.load_snapshot_from_gcs(snapshot_path, correlation_id, trace_id)
    runners = snapshot_data.get("runners", [])
    if not runners:
        LOGGER.warning(
            f"No runners found in snapshot {snapshot_path}, cannot collect stats.", extra=log_extra
        )
        return "dummy_gcs_path_for_stats"

    # 2. Loop through runners and fetch their stats
    stat_rows = []
    successful_fetches = 0
    for runner in runners:
        runner_num = runner.get("num")
        runner_name = runner.get("name", "").strip()

        if not (runner_num and runner_name):
            continue

        runner_stats: dict[str, Any] = {"num": runner_num, "name": runner_name}

        # --- a. Fetch Chrono Stats ---
        try:
            # Here we assume the runner object does not have a zone_turf_id,
            # so we rely on the resolver.
            chrono_data = zoneturf_client.get_chrono_stats(horse_name=runner_name)
            if chrono_data:
                runner_stats.update(chrono_data)
                LOGGER.info(f"Successfully fetched chrono stats for {runner_name}", extra=log_extra)
            else:
                LOGGER.warning(f"Could not fetch chrono stats for {runner_name}", extra=log_extra)

        except Exception as e:
            LOGGER.error(
                f"Error fetching chrono stats for {runner_name}: {e}",
                extra=log_extra,
                exc_info=True,
            )

        # --- b. TODO: Fetch Jockey/Entraineur Stats ---
        # j_rate, e_rate, etc. would be fetched and added here.
        # For now, these fields will be missing from the final stats payload.
        runner_stats["j_rate"] = None
        runner_stats["e_rate"] = None

        stat_rows.append(runner_stats)
        if "last_3_chrono" in runner_stats:
            successful_fetches += 1

    # 3. Assemble and save the final stats payload
    coverage = successful_fetches / len(runners) if runners else 0
    stats_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "race_doc_id": race_doc_id,
        "phase": phase,
        "coverage": coverage,
        "rows": stat_rows,
        "correlation_id": correlation_id,
        "trace_id": trace_id,
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stats_id = f"{timestamp}_{phase}_stats"

    try:
        stats_gcs_path = storage.save_snapshot(
            race_doc_id, "stats", stats_id, stats_payload, correlation_id, trace_id
        )
        LOGGER.info(f"Successfully saved aggregated stats to {stats_gcs_path}", extra=log_extra)
        return stats_gcs_path
    except Exception as e:
        LOGGER.critical(
            f"CRITICAL: Failed to save stats snapshot to GCS: {e}", extra=log_extra, exc_info=True
        )
        # Return placeholder to avoid pipeline failure, but this is a critical error.
        return "dummy_gcs_path_for_stats"
