from __future__ import annotations

import asyncio
import re
import random
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup

from hippique_orchestrator.data_contract import RaceData, RaceSnapshotNormalized, RunnerStats
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.sources_interfaces import SourceProvider
from hippique_orchestrator.utils.retry import (
    async_http_retry,
    check_for_antibot,
    check_for_retriable_status,
)
from hippique_orchestrator import config

logger = get_logger(__name__)


class GenyProvider(SourceProvider):
    """
    Fournit des statistiques complémentaires pour les chevaux, jockeys et entraîneurs
    en se basant sur Geny.com.
    """

    name = "Geny"
    BASE_URL = "https://www.geny.com"

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=config.TIMEOUT_S,
            headers={"User-Agent": "HippiqueOrchestrator/1.0 (GenyScraper)"},
            follow_redirects=True,
        )
        self._entity_cache = {}
        self._rate_limiter = asyncio.Semaphore(1)
        logger.info("GenyProvider initialized.")

    @async_http_retry
    async def _fetch_page(self, url: str) -> str:
        """Effectue un appel HTTP pour récupérer une page."""
        async with self._rate_limiter:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            response = await self._client.get(url)

            check_for_retriable_status(response)
            response.raise_for_status()

            html_content = response.text
            check_for_antibot(html_content)

            return html_content

    def _parse_stats_from_html(self, html_content: str) -> RunnerStats:
        """
        Extrait les statistiques depuis le contenu HTML d'une page entité (cheval, jockey, etc.).
        La logique de parsing est spécifique à la structure de Geny.com.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        stats = {}

        try:
            stats_table = soup.find("table", class_="table-statistiques-detaillees")
            if stats_table:
                for row in stats_table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) < 2:
                        continue

                    label = cells[0].get_text(strip=True).lower()
                    value = cells[1].get_text(strip=True)

                    if "% vict." in label:
                        rate_match = re.search(r"(\d[\d,.]*)", value)
                        if rate_match:
                            stats["driver_rate"] = float(rate_match.group(1).replace(",", ".")) / 100.0

            logger.info(f"Stats parsées depuis Geny: {stats}")

        except Exception as e:
            logger.error(f"Erreur lors du parsing des stats Geny: {e}", exc_info=True)

        return RunnerStats(
            driver_rate=stats.get("driver_rate"),
            trainer_rate=stats.get("trainer_rate"),
            source_stats="Geny",
        )

    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict[str, Any],
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> RunnerStats:
        """
        Récupère les statistiques pour un coureur, son jockey et son entraîneur depuis Geny.
        """
        jockey_name = runner_data.get("driver")
        entity_name = jockey_name
        if not entity_name:
            return RunnerStats()

        cache_key = entity_name.lower().strip()
        if cache_key in self._entity_cache:
            logger.debug(f"Cache hit for Geny stats for: {entity_name}")
            return self._entity_cache[cache_key]

        logger.info(f"Fetching Geny stats for: {entity_name}")

        entity_slug = re.sub(r'[^\w\s-]', '', entity_name).lower().replace(" ", "-")
        entity_url = f"/jockey/{entity_slug}"

        try:
            html_content = await self._fetch_page(entity_url)
        except Exception as e:
            logger.critical(
                f"Échec final de la récupération de la page pour {entity_name} sur Geny: {e}",
                exc_info=True
            )
            return RunnerStats()

        if not html_content:
            logger.warning(f"Aucun contenu HTML pour {entity_name} sur Geny après les tentatives.")
            return RunnerStats()

        entity_stats = self._parse_stats_from_html(html_content)

        if entity_stats.driver_rate or entity_stats.trainer_rate:
            self._entity_cache[cache_key] = entity_stats

        return entity_stats

    # Méthodes non implémentées pour ce provider
    async def fetch_programme(
        self, url: str, correlation_id: str | None = None, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def fetch_snapshot(
        self,
        race_url: str,
        *,
        phase: str = "H30",
        date_str: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> RaceSnapshotNormalized:
        return RaceSnapshotNormalized(
            race=RaceData(date=date.fromisoformat(date_str) if date_str else date.today(), rc_label="UNKNOWN_RC"),
            runners=[],
            source_snapshot="Geny_Not_Implemented"
        )

