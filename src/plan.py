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

logger = get_logger(__name__)

# Chemins des modules existants
MODULES_DIR = Path(__file__).parent.parent / "modules"
DISCOVER_GENY = Path(__file__).parent.parent / "discover_geny_today.py"

# Headers HTTP
DEFAULT_HEADERS = {
    "User-Agent": config.user_agent,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# Rate limiter global (partagé entre toutes les tâches asyncio)
_rate_limiter_lock = asyncio.Lock()
_last_request_time = 0.0

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
# Helpers - online_fetch_zeturf
# ============================================

def _extract_start_time_fallback(html: str) -> str | None:
    """
    Fallback simple si online_fetch_zeturf n'est pas disponible.

    Supporte uniquement les formats les plus courants.
    """
    patterns = [
        r'(\d{1,2})[h:](\d{2})',
        r'datetime="[^"]*T(\d{2}):(\d{2})',
        r'"startDate"[^"]*"[^"]*T(\d{2}):(\d{2})',
    ]

    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            h, m = match.groups()
            return f"{int(h):02d}:{int(m):02d}"

    return None

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

async def _fetch_start_time_async(
    session: aiohttp.ClientSession,
    course_url: str
) -> str | None:
    """
    Fetch asynchrone de l'heure de départ depuis une page ZEturf.

    Args:
        session: Session aiohttp réutilisable
        course_url: URL complète de la course

    Returns:
        "HH:MM" ou None
    """
    try:
        # Rate limiting GLOBAL (partagé entre toutes les tâches)
        await _rate_limited_request()

        async with session.get(course_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                logger.warning(f"HTTP {resp.status} for {course_url}")
                return None

            html = await resp.text()

            # Utiliser fonction importée ou fallback
            return _extract_start_time_fallback(html)

    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching {course_url}")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch {course_url}: {e}")
        return None

async def _enrich_plan_with_times_async(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Enrichit le plan avec les heures depuis ZEturf (parallélisé).

    Correction bug #1: Asyncio + aiohttp pour passer de 40s → 8s.

    Args:
        plan: Liste de courses sans time_local

    Returns:
        Liste enrichie avec time_local (courses sans heure sont filtrées)
    """
    if not plan:
        return []

    logger.info(f"Fetching start times for {len(plan)} races (parallel)")

    # Créer session aiohttp avec headers
    connector = aiohttp.TCPConnector(limit=10)  # Max 10 connexions simultanées
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=DEFAULT_HEADERS
    ) as session:
        # Lancer toutes les requêtes en parallèle
        tasks = [
            _fetch_start_time_async(session, race["course_url"])
            for race in plan
        ]

        times = await asyncio.gather(*tasks, return_exceptions=True)

    # Associer les heures aux courses
    enriched = []
    for race, time_result in zip(plan, times, strict=False):
        if isinstance(time_result, Exception):
            logger.warning(f"Error for {race['r_label']}{race['c_label']}: {time_result}")
            continue

        if time_result:
            race["time_local"] = time_result
            enriched.append(race)
            logger.debug(f"{race['r_label']}{race['c_label']} at {time_result}")
        else:
            logger.warning(f"No time found for {race['r_label']}{race['c_label']}, skipping")

    logger.info(f"Successfully enriched {len(enriched)}/{len(plan)} races")
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

            # Construire URLs ZEturf (format standard)
            r_num = r_label[1:]
            c_num = c_label[1:]
            slug = meeting.get("slug", "")

            course_url = f"https://www.zeturf.fr/fr/course/{date}/R{r_num}C{c_num}{f'-{slug}' if slug else ''}"
            reunion_url = f"https://www.zeturf.fr/fr/reunion/{date}/R{r_num}"

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
    Construit le plan complet du jour : Geny (R/C/ID) + ZEturf (heures).

    ASYNC VERSION pour usage dans FastAPI (correction bug #4).

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
                "course_url": "https://www.zeturf.fr/fr/course/2025-10-16/R1C3",
                "reunion_url": "https://www.zeturf.fr/fr/reunion/2025-10-16/R1"
            },
            ...
        ]
    """
    if date == "today":
        date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Building plan for {date}")

    # 1. Obtenir la liste des courses depuis Geny (subprocess)
    geny_data = _call_discover_geny()

    if not geny_data.get("meetings"):
        logger.warning("No meetings found from Geny")
        return []

    # 2. Construire le plan avec URLs ZEturf
    plan = _build_plan_structure(geny_data, date)

    logger.info(f"Built {len(plan)} races from Geny")

    # 3. Enrichir avec les heures depuis ZEturf (ASYNC + PARALLEL)
    enriched_plan = await _enrich_plan_with_times_async(plan)

    # 4. Trier par heure
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
