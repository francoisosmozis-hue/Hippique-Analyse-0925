"""
src/plan.py - Construction du Plan du Jour

Combine Geny (R/C/ID) + ZEturf (heures) pour construire le planning complet.

Architecture:
  - discover_geny_today.py (subprocess) → liste R/C/ID
  - online_fetch_zeturf._extract_start_time() (import) → heures ZEturf
  - Asyncio + aiohttp pour fetch parallèle (40s → 8s)
  - Rate limiter global partagé (respect 1 req/s par hôte)

Corrections v3:
  - ✅ Asyncio avec build_plan_async() pour FastAPI
  - ✅ Rate limiter global (lock partagé)
  - ✅ Import _extract_start_time depuis online_fetch_zeturf.py
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, date as date_obj
from typing import Any
from zoneinfo import ZoneInfo

from hippique_orchestrator import config, data_source
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)


async def build_plan_async(date_str: str) -> list[dict[str, Any]]:
    """
    Construit le plan complet du jour en utilisant Boturfers comme unique source.
    """
    if date_str == "today":
        date_str = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")

    logger.info(f"Building plan for {date_str} using Boturfers as the single source.")

    # Convert to date objects for robust comparison
    try:
        req_date = date_obj.fromisoformat(date_str)
    except (ValueError, TypeError):
        logger.warning(f"Invalid date string format: '{date_str}'. Defaulting to today.")
        req_date = datetime.now(ZoneInfo(config.TIMEZONE)).date()
        date_str = req_date.isoformat()

    today = datetime.now(ZoneInfo(config.TIMEZONE)).date()
    tomorrow = today + timedelta(days=1)

    if req_date == today:
        programme_url = "https://www.boturfers.fr/programme-pmu-du-jour"
    elif req_date == tomorrow:
        programme_url = "https://www.boturfers.fr/programme-pmu-demain"
    else:
        programme_url = f"https://www.boturfers.fr/courses/{date_str}"

    logger.info(f"Using Boturfers programme URL: {programme_url}")

    # 1. Obtenir le programme depuis la source de données (Boturfers)
    source_data = await data_source.fetch_programme(programme_url)

    if not source_data or not source_data.get("races"):
        logger.warning("Failed to fetch programme from Boturfers or it was empty.")
        return []

    logger.info(f"Successfully fetched {len(source_data.get('races', []))} races from Boturfers.")

    # 2. Construire le plan directement depuis les données Boturfers
    enriched_plan = []
    for race_source in source_data["races"]:
        if race_source.get("start_time"):
            # Extrait R et C de "R1 C1"
            rc_match = re.match(r"(R\d+)\s*(C\d+)", race_source.get("rc", ""))
            if not rc_match:
                logger.warning(
                    f"Could not parse R/C from '{race_source.get('rc')}'. Skipping race."
                )
                continue
            r_label, c_label = rc_match.groups()

            enriched_plan.append(
                {
                    "date": date,
                    "r_label": r_label,
                    "c_label": c_label,
                    "course_id": None,  # Geny ID n'est plus disponible
                    "meeting": race_source.get(
                        "name", ""
                    ),  # Le nom de la course est utilisé comme meeting
                    "time_local": race_source["start_time"],
                    "course_url": race_source["url"],
                    "reunion_url": None,  # L'URL de la réunion n'est plus disponible
                    "partants": int(race_source.get("runners_count"))
                    if race_source.get("runners_count")
                    and str(race_source.get("runners_count")).isdigit()
                    else None,
                }
            )

    # 3. Trier par heure
    if enriched_plan:
        enriched_plan.sort(key=lambda x: x["time_local"])

    logger.info(f"Plan complete: {len(enriched_plan)} races with times")
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
        return asyncio.run(build_plan_async(date))
    except RuntimeError as e:
        if "cannot run" in str(e).lower():
            logger.error(
                "Cannot use build_plan() from within event loop. Use build_plan_async() instead."
            )
            raise RuntimeError("Use build_plan_async() in async context") from e
        raise
