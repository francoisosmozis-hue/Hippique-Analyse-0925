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
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

from src.config import config
from src.logging_utils import get_logger
from src.online_fetch_boturfers import fetch_boturfers_programme

logger = get_logger(__name__)

# Chemins des modules existants
MODULES_DIR = Path(__file__).parent.parent / "modules"
DISCOVER_GENY = Path(__file__).parent.parent / "discover_geny_today.py"





# ============================================
# Helpers - discover_geny_today.py
# ============================================

def _call_discover_geny() -> dict[str, Any]:
    """
    Appelle discover_geny_today.py pour obtenir la liste des courses.

    Returns:
        {
            "date": "2025-10-16",
            "meetings": [
                {
                    "r": "R1",
                    "hippo": "Paris-Vincennes (FR)",
                    "slug": "paris-vincennes",
                    "courses": [
                        {"c": "C1", "id_course": "12345"},
                        {"c": "C3", "id_course": "12346"}
                    ]
                }
            ]
        }
    """
    if not DISCOVER_GENY.exists():
        logger.error(f"discover_geny_today.py not found at {DISCOVER_GENY}")
        return {"date": datetime.now().strftime("%Y-%m-%d"), "meetings": []}

    try:
        result = subprocess.run(
            [sys.executable, str(DISCOVER_GENY)],
            check=False, capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(f"discover_geny_today.py failed: {result.stderr}")
            return {"date": datetime.now().strftime("%Y-%m-%d"), "meetings": []}

        data = json.loads(result.stdout)
        logger.info(f"Discovered {len(data.get('meetings', []))} meetings from Geny")
        return data

    except Exception as e:
        logger.error(f"Failed to call discover_geny_today.py: {e}", exc_info=e)
        return {"date": datetime.now().strftime("%Y-%m-%d"), "meetings": []}



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
# Fetch Async
# ============================================



async def _enrich_plan_with_times_async(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Enrichit le plan avec les heures et les URLs depuis Boturfers.

    Args:
        plan: Liste de courses sans time_local et avec URLs ZEturf provisoires.

    Returns:
        Liste enrichie avec time_local et URLs Boturfers (courses sans heure sont filtrées).
    """
    if not plan:
        logger.info("Plan from Geny is empty, skipping Boturfers enrichment.")
        return []

    logger.info("Fetching programme from Boturfers to enrich plan.")

    boturfers_programme_url = "https://www.boturfers.fr/programme-pmu-du-jour"
    boturfers_data = await asyncio.to_thread(fetch_boturfers_programme, boturfers_programme_url)
    logger.info(f"Boturfers programme data received: {json.dumps(boturfers_data, indent=2)}")

    if not boturfers_data or not boturfers_data.get("races"):
        logger.warning("Failed to fetch Boturfers programme or it was empty.")
        return []

    # Créer un mapping rapide des courses Boturfers par "R_C"
    boturfers_races_map = {}
    for race in boturfers_data["races"]:
        # Nettoyer le format "R1C1" pour correspondre à celui de Geny
        rc_key = f"{race['reunion']}{race['rc'].split(race['reunion'])[1].strip()}"
        boturfers_races_map[rc_key] = race
    logger.info(f"Boturfers races map keys: {list(boturfers_races_map.keys())}")

    enriched = []
    for race_geny in plan:
        geny_rc_key = f"{race_geny['r_label']}{race_geny['c_label']}"
        logger.debug(f"Attempting to match Geny race {geny_rc_key}")
        
        if geny_rc_key in boturfers_races_map:
            race_boturfers = boturfers_races_map[geny_rc_key]
            if race_boturfers.get("start_time"):
                race_geny["time_local"] = race_boturfers["start_time"]
                race_geny["course_url"] = race_boturfers["url"] # Mettre à jour avec l'URL Boturfers
                enriched.append(race_geny)
                logger.debug(f"Enriched {geny_rc_key} with time {race_geny['time_local']} and URL {race_geny['course_url']} from Boturfers.")
            else:
                logger.warning(f"No start_time found for {geny_rc_key} in Boturfers data, skipping.")
        else:
            logger.warning(f"No matching Boturfers race found for Geny race {geny_rc_key}, skipping.")

    logger.info(f"Successfully enriched {len(enriched)}/{len(plan)} races from Boturfers.")
    return enriched

# ============================================
# Build Plan Structure
# ============================================

def _build_plan_structure(geny_data: dict[str, Any], date: str) -> list[dict[str, Any]]:
    """
    Construit la structure du plan à partir des données Geny.

    Args:
        geny_data: Output de discover_geny_today.py
        date: YYYY-MM-DD

    Returns:
        Liste de courses avec URLs ZEturf (sans time_local)
    """
    plan = []
    seen = set()  # Déduplication par (R, C)

    for meeting in geny_data.get("meetings", []):
        r_label = meeting["r"]
        meeting_name = meeting.get("hippo", "")

        for course_data in meeting.get("courses", []):
            c_label = course_data["c"]
            course_id = course_data.get("id_course", "")

            # Déduplication
            key = (r_label, c_label)
            if key in seen:
                continue
            seen.add(key)

            # URLs will be populated by _enrich_plan_with_times_async from Boturfers
            course_url = None
            reunion_url = None

            plan.append({
                "date": date,
                "r_label": r_label,
                "c_label": c_label,
                "course_id": course_id,
                "meeting": meeting_name,
                "course_url": course_url,
                "reunion_url": reunion_url,
                # time_local sera ajouté par _enrich_plan_with_times_async
            })

    return plan

# ============================================
# Public API
# ============================================

async def build_plan_async(date: str) -> list[dict[str, Any]]:
    """
    Construit le plan complet du jour : Geny (R/C/ID) + Boturfers (heures et URLs).

    ASYNC VERSION pour usage dans FastAPI.

    Args:
        date: YYYY-MM-DD ou "today"

    Returns:
        Liste triée par heure
        [
            {
                "date": "2025-10-16",
                "r_label": "R1",
                "c_label": "C3",
                "course_id": "12346",
                "meeting": "Paris-Vincennes (FR)",
                "time_local": "14:30",
                "course_url": "https://www.boturfers.fr/course/...",
                "reunion_url": "https://www.zeturf.fr/fr/reunion/2025-10-16/R1" # ZEturf reunion URL still used for now
            },
            ...
        ]
    """
    if date == "today":
        date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Building plan for {date}")

    # 1. Obtenir la liste des courses depuis Geny (subprocess)
    geny_data = _call_discover_geny()
    logger.info(f"DEBUG: Geny data received: {json.dumps(geny_data, indent=2)}")

    if not geny_data.get("meetings"):
        logger.warning("No meetings found from Geny")
        return []

    # 2. Construire le plan avec URLs ZEturf
    plan = _build_plan_structure(geny_data, date)
    logger.info(f"DEBUG: Plan structure built from Geny data: {json.dumps(plan, indent=2)}")


    # 3. Enrichir avec les heures depuis Boturfers
    enriched_plan = await _enrich_plan_with_times_async(plan)
    logger.info(f"DEBUG: Enriched plan after Boturfers: {json.dumps(enriched_plan, indent=2)}")

    # 4. Trier par heure
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
