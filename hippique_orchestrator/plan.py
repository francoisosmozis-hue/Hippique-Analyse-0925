"""
src/plan.py - Construction du Plan du Jour

This module builds the complete daily race schedule by fetching data from the
configured providers via the programme_provider.
"""

from __future__ import annotations

import asyncio
from datetime import date as date_obj, datetime
from typing import Any, List
from starlette.concurrency import run_in_threadpool

from hippique_orchestrator.data_contract import Race
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.programme_provider import get_races_for_date

logger = get_logger(__name__)


async def build_plan_async(date_str: str) -> List[Dict[str, Any]]:
    """
    Builds the daily race plan by fetching data using the new provider architecture.
    This version runs the synchronous get_races_for_date in a thread pool.
    """
    logger.info(f"Building race plan for date: {date_str}")
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        logger.error(f"Invalid date format for build_plan_async: '{date_str}'")
        return []

    # Use run_in_threadpool to call the synchronous get_races_for_date
    # without blocking the asyncio event loop.
    races: List[Race] = await run_in_threadpool(get_races_for_date, target_date)

    if not races:
        logger.warning(f"No races found for {date_str}. Returning empty plan.")
        return []

    # Convert Race objects to dictionaries for the response
    plan = [race.model_dump(mode='json') for race in races]
    logger.info(f"Successfully built plan with {len(plan)} races for {date_str}.")
    return plan


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
    except RuntimeError:
        # If no event loop is running, create one.
        return asyncio.run(build_plan_async(date))
