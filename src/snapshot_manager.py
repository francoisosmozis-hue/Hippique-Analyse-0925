"""
src/snapshot_manager.py - Module pour gérer les snapshots de courses.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from hippique_orchestrator.online_fetch_boturfers import BoturfersFetcher, normalize_snapshot
from hippique_orchestrator.plan import build_plan_async # Assuming this can list all races for a day

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"

async def write_snapshot_for_day(
    date_str: str,
    race_urls: Optional[List[str]] = None,
    phase: str = "H9",
    correlation_id: Optional[str] = None,
) -> List[Path]:
    """
    Fetches snapshots for all French races of a given day (or specified URLs)
    and writes them to files with the specified phase label.

    Args:
        date_str: Date in YYYY-MM-DD format.
        race_urls: Optional list of specific race URLs to snapshot. If None,
                   all French races for the day will be discovered.
        rc_labels: Optional list of RNC labels corresponding to race_urls.
        phase: The phase label for the snapshot (e.g., "H9", "H30", "H5").
        correlation_id: Optional correlation ID for logging.

    Returns:
        A list of paths to the generated snapshot files.
    """
    logger.info(
        f"Starting snapshot for day {date_str} (phase: {phase})",
        extra={"correlation_id": correlation_id, "date": date_str, "phase": phase},
    )

    if not race_urls:
        # Discover all French races for the day
        logger.info(
            f"Discovering races for {date_str}...",
            extra={"correlation_id": correlation_id},
        )
        plan = await build_plan_async(date_str)
        if not plan:
            logger.warning(
                f"No races found for {date_str}. Skipping snapshot.",
                extra={"correlation_id": correlation_id},
            )
            return []
        race_urls = [race["course_url"] for race in plan]
        rc_labels = [f"{race['r_label']}{race['c_label']}" for race in plan]
        logger.info(
            f"Discovered {len(race_urls)} races for {date_str}.",
            extra={"correlation_id": correlation_id, "num_races": len(race_urls)},
        )

    generated_files: List[Path] = []
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    phase_tag = phase.replace("-", "").upper() # Ensure consistent tag like H9, H30, H5

    for i, url in enumerate(race_urls):
        rc_label = rc_labels[i] if rc_labels and i < len(rc_labels) else "UNKNOWN"
        try:
            fetcher = BoturfersFetcher(race_url=url)
            raw_snapshot = fetcher.get_snapshot()

            if "error" in raw_snapshot or not raw_snapshot.get("runners"):
                logger.error(
                    f"Scraping failed or returned no runners for {url}. Skipping.",
                    extra={"correlation_id": correlation_id, "url": url},
                )
                continue
            
            normalized_data = normalize_snapshot(raw_snapshot)
            
            rc_dir = DATA_DIR / rc_label
            rc_dir.mkdir(parents=True, exist_ok=True)

            filename = f"{timestamp}_{phase_tag}.json"
            output_path = rc_dir / filename
            output_path.write_text(json.dumps(normalized_data, ensure_ascii=False, indent=2), encoding="utf-8")
            generated_files.append(output_path)
            logger.info(
                f"Snapshot for {rc_label} ({phase}) written to {output_path}",
                extra={"correlation_id": correlation_id, "rc_label": rc_label, "path": str(output_path)},
            )

        except Exception as e:
            logger.error(
                f"Error processing snapshot for {url}: {e}",
                exc_info=True,
                extra={"correlation_id": correlation_id, "url": url},
            )
            continue
            
    logger.info(
        f"Completed snapshot for day {date_str} (phase: {phase}). Generated {len(generated_files)} files.",
        extra={"correlation_id": correlation_id, "date": date_str, "phase": phase, "num_files": len(generated_files)},
    )
    return generated_files
