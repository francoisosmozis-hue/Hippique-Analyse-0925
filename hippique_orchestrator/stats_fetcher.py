"""
Fetches and aggregates statistics for a given race, using the new StatsProvider architecture.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from . import storage
from .config import get_config
from .stats_provider import ZoneTurfProvider

LOGGER = logging.getLogger(__name__)


def collect_stats(
    race_doc_id: str,
    phase: str,
    date: str, # Keep for potential future use
    correlation_id: str | None = None,
    trace_id: str | None = None,
) -> str:
    """
    Orchestrates the collection of all stats for the runners in a race using a StatsProvider.
    Saves the aggregated stats to GCS and returns the path.
    """
    log_extra = {"correlation_id": correlation_id, "trace_id": trace_id, "race_doc_id": race_doc_id}
    LOGGER.info(f"Starting stats collection for {race_doc_id} using StatsProvider", extra=log_extra)

    # 1. Load snapshot data to get runner list
    latest_snapshot_meta = storage.get_latest_snapshot_metadata(race_doc_id, phase, correlation_id, trace_id)
    if not (latest_snapshot_meta and latest_snapshot_meta.get("gcs_snapshot_path")):
        LOGGER.error(f"Cannot collect stats, no snapshot found for {race_doc_id} in phase {phase}", extra=log_extra)
        return "dummy_gcs_path_for_stats" 

    snapshot_path = latest_snapshot_meta["gcs_snapshot_path"]
    snapshot_data = storage.load_snapshot_from_gcs(snapshot_path, correlation_id, trace_id)
    runners = snapshot_data.get("runners", [])
    if not runners:
        LOGGER.warning(f"No runners found in snapshot {snapshot_path}, cannot collect stats.", extra=log_extra)
        return "dummy_gcs_path_for_stats"

    # 2. Instantiate the provider
    config = get_config()
    zt_config = config.data_sources.get("zoneturf", {})
    provider = ZoneTurfProvider(config=zt_config)

    # 3. Loop through runners and fetch their stats
    stat_rows = []
    successful_fetches = 0
    for runner in runners:
        runner_num = runner.get("num")
        horse_name = runner.get("name", "").strip()
        jockey_name = runner.get("jockey", "").strip()
        trainer_name = runner.get("entraineur", "").strip()

        if not all([runner_num, horse_name, jockey_name, trainer_name]):
            continue

        # Using the user-defined JSON contract for the output structure
        # We assume no known_ids are passed for now, forcing resolution
        jockey_stats = provider.fetch_jockey_stats(jockey_name=jockey_name)
        trainer_stats = provider.fetch_trainer_stats(trainer_name=trainer_name)
        chrono_stats = provider.fetch_horse_chrono(horse_name=horse_name)

        # Assemble the row as per the new contract
        runner_output = {
            "num": runner_num,
            "horse_name": horse_name,
            "jockey_name": jockey_name,
            "trainer_name": trainer_name,
            "jockey_stats": jockey_stats.model_dump() if jockey_stats else None,
            "trainer_stats": trainer_stats.model_dump() if trainer_stats else None,
            "chrono": chrono_stats.model_dump() if chrono_stats else None,
            "quality": {
                "complete": all([jockey_stats, trainer_stats, chrono_stats]),
                "missing_fields": [
                    field for field, data in [
                        ("jockey_stats", jockey_stats), 
                        ("trainer_stats", trainer_stats), 
                        ("chrono", chrono_stats)
                    ] if not data
                ]
            }
        }
        stat_rows.append(runner_output)
        if runner_output["quality"]["complete"]:
            successful_fetches += 1

    # 4. Assemble and save the final stats payload
    coverage = successful_fetches / len(runners) if runners else 0
    stats_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "race_doc_id": race_doc_id,
        "phase": phase,
        "coverage": coverage,
        "rows": stat_rows,
        "correlation_id": correlation_id,
        "trace_id": trace_id
    }
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stats_id = f"{timestamp}_{phase}_stats"
    
    try:
        stats_gcs_path = storage.save_snapshot(race_doc_id, "stats", stats_id, stats_payload, correlation_id, trace_id)
        LOGGER.info(f"Successfully saved aggregated stats to {stats_gcs_path}", extra=log_extra)
        return stats_gcs_path
    except Exception as e:
        LOGGER.critical(f"CRITICAL: Failed to save stats snapshot to GCS: {e}", extra=log_extra, exc_info=True)
        return "dummy_gcs_path_for_stats"