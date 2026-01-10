"""
snapshot_manager.py - Manages the creation of daily snapshots.
"""

from __future__ import annotations

import asyncio

from hippique_orchestrator import config
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.plan import build_plan_async
from hippique_orchestrator.runner import run_course

logger = get_logger(__name__)


async def _run_course_with_semaphore(
    semaphore: asyncio.Semaphore,
    course_url: str,
    phase: str,
    date: str,
    correlation_id: str,
):
    """
    Acquires a semaphore before running a course and releases it afterwards.
    """
    async with semaphore:
        await run_course(
            course_url=course_url, phase=phase, date=date, correlation_id=correlation_id
        )


async def write_snapshot_for_day_async(
    date_str: str,
    phase: str,
    race_urls: list[str] | None = None,
    rc_labels: list[str] | None = None,
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

    semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_SNAPSHOT_TASKS)

    try:
        plan = await build_plan_async(date_str)
        if not plan:
            logger.warning(
                f"No race plan found for {date_str}. No snapshots will be created.",
                extra={"correlation_id": correlation_id},
            )
            return

        logger.info(
            f"Found {len(plan)} races for {date_str}. Creating {config.MAX_CONCURRENT_SNAPSHOT_TASKS} concurrent snapshots...",
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

            task = asyncio.create_task(
                _run_course_with_semaphore(
                    semaphore,
                    course_url=course_url,
                    phase=phase,
                    date=date,
                    correlation_id=correlation_id,
                )
            )
            snapshot_tasks.append(task)

        await asyncio.gather(*snapshot_tasks)

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
    race_urls: list[str] | None = None,
    rc_labels: list[str] | None = None,
    correlation_id: str = "N/A",
):
    """
    Sync wrapper for the async snapshot creation function.
    """
    asyncio.run(
        write_snapshot_for_day_async(
            date_str=date_str,
            phase=phase,
            race_urls=race_urls,
            rc_labels=rc_labels,
            correlation_id=correlation_id,
        )
    )
