"""
Fetches and aggregates statistics for a given race, including chrono data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from . import gcs_client
from .source_registry import source_registry

LOGGER = logging.getLogger(__name__)


async def collect_stats(
    race_doc_id: str,
    phase: str,
    date: str,  # Keep for potential future use
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> str:
    """
    Orchestrates the collection of all stats for the runners in a race using the primary snapshot provider.
    Saves the aggregated stats to GCS and returns the path.
    """
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "race_doc_id": race_doc_id}
    LOGGER.info(f"Starting stats collection for {race_doc_id}", extra=log_extra)

    # 1. Get the list of runners from the main race document
    latest_snapshot_meta = await gcs_client.get_latest_snapshot_metadata(
        race_doc_id, phase, correlation_id, trace_id
    )
    if not (latest_snapshot_meta and latest_snapshot_meta.get("gcs_snapshot_path")):
        LOGGER.error(
            f"Cannot collect stats, no snapshot found for {race_doc_id} in phase {phase}",
            extra=log_extra,
        )
        return "dummy_gcs_path_for_stats"

    snapshot_path = latest_snapshot_meta["gcs_snapshot_path"]
    snapshot_data = await gcs_client.load_snapshot_from_gcs(snapshot_path, correlation_id, trace_id)
    runners_data = snapshot_data.get("runners", [])
    discipline = snapshot_data.get("discipline", "unknown") # Get discipline from snapshot

    if not runners_data:
        LOGGER.warning(
            f"No runners found in snapshot {snapshot_path}, cannot collect stats.", extra=log_extra
        )
        return "dummy_gcs_path_for_stats"

    # Get the primary snapshot provider
    try:
        provider = source_registry.get_primary_snapshot_provider()
    except (ValueError, TypeError) as e:
        LOGGER.error(f"Failed to get primary snapshot provider for stats collection: {e}", extra=log_extra)
        return "dummy_gcs_path_for_stats"
    
    if not provider:
        LOGGER.error("No primary snapshot provider available for stats collection.", extra=log_extra)
        return "dummy_gcs_path_for_stats"


    # 2. Loop through runners and fetch their stats using the primary snapshot provider
    stat_rows = []

    for runner_raw_data in runners_data:
        runner_num = runner_raw_data.get("num")
        runner_name = runner_raw_data.get("name", "").strip() # Use 'name' key for consistency

        if not (runner_num and runner_name):
            LOGGER.warning(f"Skipping runner due to missing num or name: {runner_raw_data}", extra=log_extra)
            continue

        LOGGER.info(
            f"Fetching stats for runner {runner_name} (discipline: {discipline})",
            extra={**log_extra, "runner_name": runner_name, "discipline": discipline},
        )

        # Call the primary snapshot provider to fetch all relevant stats for the runner
        all_runner_stats: Dict[str, Any] = await provider.fetch_stats_for_runner(
            runner_name=runner_name,
            discipline=discipline,
            runner_data=runner_raw_data, # Pass full runner data
            correlation_id=correlation_id,
            trace_id=trace_id,
        )

        # Combine base runner info with fetched stats
        combined_stats = {
            "num": runner_num,
            "name": runner_name,
            **all_runner_stats,
        }
        stat_rows.append(combined_stats)

    # 3. Assemble and save the final stats payload
    total_runners = len(runners_data) if runners_data else 1

    # Basic coverage: count how many runners have any stats beyond basic info
    covered_runners_count = sum(
        1 for r_stats in stat_rows if len(r_stats) > 2 # num and name are always present
    )
    coverage = covered_runners_count / total_runners

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
        stats_gcs_path = await gcs_client.save_snapshot(
            race_doc_id, "stats", stats_id, stats_payload, correlation_id, trace_id
        )
        LOGGER.info(f"Successfully saved aggregated stats to {stats_gcs_path}", extra=log_extra)
        return stats_gcs_path
    except Exception as e:
        LOGGER.critical(
            f"CRITICAL: Failed to save stats snapshot to GCS: {e}", extra=log_extra, exc_info=True
        )
        return "dummy_gcs_path_for_stats"
