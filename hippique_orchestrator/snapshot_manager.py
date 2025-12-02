"""
snapshot_manager.py - Manages the creation of daily snapshots.
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from hippique_orchestrator.plan import build_plan_async
from hippique_orchestrator.runner import run_course
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)

async def write_snapshot_for_day_async(
    date_str: str,
    phase: str,
    race_urls: Optional[List[str]] = None,
    rc_labels: Optional[List[str]] = None,
    correlation_id: str = "N/A",
):
    """
    Asynchronously fetches the race plan for a given day and triggers
    the snapshot creation for each race.
    """
    logger.info(
        f"Starting daily snapshot job for {date_str}, phase {phase}",
        extra={"correlation_id": correlation_id, "date": date_str, "phase": phase},
    )

    try:
        plan = await build_plan_async(date_str)
        if not plan:
            logger.warning(
                f"No race plan found for {date_str}. No snapshots will be created.",
                extra={"correlation_id": correlation_id},
            )
            return

        logger.info(
            f"Found {len(plan)} races for {date_str}. Creating snapshots...",
            extra={"correlation_id": correlation_id, "num_races": len(plan)},
        )

        snapshot_tasks = []
        for race in plan:
            course_url = race.get("course_url")
            date = race.get("date")

            if not course_url or not date:
                logger.warning(
                    f"Skipping race with incomplete data: {race}",
                    extra={"correlation_id": correlation_id},
                )
                continue

            # The new way to run the analysis
            run_course(
                course_url=course_url,
                phase=phase,
                date=date,
                correlation_id=correlation_id
            )
            snapshot_tasks.append(course_url) # Keep track of what was processed
            
        logger.info(
            f"Finished creating {len(snapshot_tasks)} snapshot tasks for {date_str}.",
            extra={"correlation_id": correlation_id},
        )

    except Exception as e:
        logger.error(
            f"Failed during daily snapshot job for {date_str}: {e}",
            exc_info=True,
            extra={"correlation_id": correlation_id},
        )

def write_snapshot_for_day(
    date_str: str,
    phase: str,
    race_urls: Optional[List[str]] = None,
    rc_labels: Optional[List[str]] = None,
    correlation_id: str = "N/A",
):
    """
    Sync wrapper for the async snapshot creation function.
    """
    asyncio.run(write_snapshot_for_day_async(
        date_str=date_str,
        phase=phase,
        race_urls=race_urls,
        rc_labels=rc_labels,
        correlation_id=correlation_id
    ))
