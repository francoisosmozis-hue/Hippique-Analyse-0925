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
from typing import Any

import asyncio
import re
from datetime import datetime, timedelta, date as date_obj
from hippique_orchestrator.analysis_utils import coerce_partants
from zoneinfo import ZoneInfo

from hippique_orchestrator import config
from hippique_orchestrator.source_registry import source_registry
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.programme_provider import programme_provider

logger = get_logger(__name__)


async def build_plan_async(date_str: str) -> list[dict[str, Any]]:
    """
    Construit le plan complet du jour en utilisant la stratégie multi-sources du ProgrammeProvider.
    """
    if date_str == "today":
        date_obj_req = datetime.now(ZoneInfo(config.TIMEZONE)).date()
    else:
        try:
            date_obj_req = date_obj.fromisoformat(date_str)
        except (ValueError, TypeError):
            logger.warning(f"Invalid date string format: '{date_str}'. Defaulting to today.")
            date_obj_req = datetime.now(ZoneInfo(config.TIMEZONE)).date()
    
    date_str = date_obj_req.isoformat()
    logger.info(f"Building plan for {date_str} using ProgrammeProvider.")

    # 1. Obtenir le programme via le ProgrammeProvider
    source_data = await programme_provider.get_programme(date_obj_req)

    if not source_data:
        logger.warning(f"Failed to fetch programme for {date_str} from any source.")
        return []

    logger.info(f"Successfully fetched {len(source_data)} races for {date_str}.")

    # 2. Construire le plan directement depuis les données du programme
    enriched_plan = []
    for race_source in source_data:
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
                    "date": date_str,
                    "r_label": r_label,
                    "c_label": c_label,
                    "course_id": None,  # Geny ID n'est plus disponible
                    "meeting": race_source.get(
                        "name", ""
                    ),  # Le nom de la course est utilisé comme meeting
                    "time_local": race_source["start_time"].replace('h', ':'),
                    "course_url": race_source["url"],
                    "reunion_url": None,  # L'URL de la réunion n'est plus disponible
                    "partants": coerce_partants(race_source.get("runners_count"))
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
