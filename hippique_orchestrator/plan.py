"""
src/plan.py - Construction du Plan du Jour

This module builds the complete daily race schedule by fetching data from the
configured providers via the programme_provider.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date as date_obj, datetime
from typing import Any, Dict, List

from starlette.concurrency import run_in_threadpool

from hippique_orchestrator.data_contract import Race
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.programme_provider import get_programme_for_date

logger = get_logger(__name__)


async def build_plan_async(date_str: str) -> List[Dict[str, Any]]:
    """
    Builds the daily race plan by fetching data using the new provider architecture.
    This version runs the synchronous get_programme_for_date in a thread pool.
    """
    logger.info(f"Building race plan for date: {date_str}")
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        logger.error(f"Invalid date format for build_plan_async: '{date_str}'")
        return []

    # Use run_in_threadpool to call the synchronous get_programme_for_date
    # without blocking the asyncio event loop.
    programme = await run_in_threadpool(get_programme_for_date, target_date)

    if not programme or not programme.races:
        logger.warning(f"No programme or races found for {date_str}. Returning empty plan.")
        return []

    enriched_plan = []
    for race in programme.races:
        if not isinstance(race, Race) or not race.rc or not race.start_time:
            logger.warning(f"Skipping malformed race data: {race}")
            continue

        rc_match = re.match(r"R(\d+)\s*C(\d+)", race.rc)
        if not rc_match:
            logger.warning(f"Skipping race with invalid RC format: {race.rc}")
            continue

        r_label = f"R{rc_match.group(1)}"
        c_label = f"C{rc_match.group(2)}"

        partants = None
        if race.runners_count:
            if isinstance(race.runners_count, str):
                count_match = re.search(r"\d+", race.runners_count)
                if count_match:
                    partants = int(count_match.group(0))
            elif isinstance(race.runners_count, int):
                partants = race.runners_count
        
        race_dict = race.model_dump()

        enriched_plan.append(
            {
                **race_dict,
                "race_id": race_dict.get("race_id") or f"{r_label}{c_label}",
                "r_label": r_label,
                "c_label": c_label,
                "partants": partants,
                "hippodrome_label": race_dict.get("hippodrome"),
                "time_local": race.start_time.strftime("%H:%M") if race.start_time else None,
                "meeting": race.name,
                "course_url": race.url,
                "date": race.date.isoformat() if race.date else None,
            }
        )

    if enriched_plan:
        enriched_plan.sort(key=lambda x: x["time_local"])
    
    logger.info(f"Successfully built plan with {len(enriched_plan)} races for {date_str}.")
    return enriched_plan


def build_plan(date: str) -> list[dict[str, Any]]:
    """
    Version SYNCHRONE de build_plan_async().

    ⚠️ DEPRECATED: Utiliser build_plan_async() dans FastAPI.

    Cette fonction existe uniquement pour compatibilité avec les tests synchrones.
    Ne pas utiliser dans le code FastAPI (provoque RuntimeError).
    """
    logger.warning("build_plan() is deprecated, use build_plan_async() instead")

    try:
        # If an event loop is running, delegate to it.
        loop = asyncio.get_running_loop()
        return loop.run_until_complete(build_plan_async(date))
    except RuntimeError as e:
        if "cannot run loop while another is running" in str(e):
             raise RuntimeError(
                "build_plan cannot be called from a running event loop. "
                "Use build_plan_async() in async context."
            ) from e
        # If no event loop is running, create one.
        return asyncio.run(build_plan_async(date))
