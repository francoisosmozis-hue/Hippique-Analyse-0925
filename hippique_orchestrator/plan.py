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
import time
from datetime import datetime
from typing import Any

from hippique_orchestrator import data_source
from hippique_orchestrator.config import get_config
from hippique_orchestrator.logging_utils import get_logger

config = get_config()

logger = get_logger(__name__)



# ============================================
# Rate Limiter Global
# ============================================

async def _rate_limited_request():
    """
    Rate limiter global partagé entre toutes les tâches asyncio.

    Garantit qu'il y a au moins 1/requests_per_second secondes entre chaque requête.

    Correction bug #5: Lock global plutôt que await asyncio.sleep() dans chaque tâche.
    """
    global _last_request_time

    async with _rate_limiter_lock:
        now = time.time()
        min_interval = 1.0 / config.requests_per_second
        time_since_last = now - _last_request_time

        if time_since_last < min_interval:
            wait_time = min_interval - time_since_last
            await asyncio.sleep(wait_time)

        _last_request_time = time.time()

# ============================================
# Public API
# ============================================

async def build_plan_async(date: str) -> list[dict[str, Any]]:
    """
    Construit le plan complet du jour en utilisant Boturfers comme unique source.
    """
    if date == "today":
        date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Building plan for {date} using Boturfers as the single source.")

    # 1. Obtenir le programme depuis la source de données (Boturfers)
    if date == datetime.now().strftime("%Y-%m-%d"):
        programme_url = "https://www.boturfers.fr/programme-pmu-du-jour"
    else:
        programme_url = f"https://www.boturfers.fr/courses/{date}"
    source_data = await asyncio.to_thread(data_source.fetch_programme, programme_url)

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
                logger.warning(f"Could not parse R/C from '{race_source.get('rc')}'. Skipping race.")
                continue
            r_label, c_label = rc_match.groups()

            enriched_plan.append({
                "date": date,
                "r_label": r_label,
                "c_label": c_label,
                "course_id": None,  # Geny ID n'est plus disponible
                "meeting": race_source.get("name", ""), # Le nom de la course est utilisé comme meeting
                "time_local": race_source["start_time"],
                "course_url": race_source["url"],
                "reunion_url": None, # L'URL de la réunion n'est plus disponible
            })

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
            logger.error("Cannot use build_plan() from within event loop. Use build_plan_async() instead.")
            raise RuntimeError("Use build_plan_async() in async context") from e
        raise
