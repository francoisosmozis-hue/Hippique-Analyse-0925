from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any

import httpx
from bs4 import BeautifulSoup

from hippique_orchestrator.data_contract import RaceData, RaceSnapshotNormalized, RunnerStats
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.sources_interfaces import SourceProvider

logger = get_logger(__name__)


class GenyProvider(SourceProvider):
    """
    Fournit des statistiques complémentaires pour les chevaux, jockeys et entraîneurs
    en se basant sur Geny.com.
    """

    name = "Geny"
    BASE_URL = "https://www.geny.com"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=15.0,
            headers={"User-Agent": "HippiqueOrchestrator/1.0 (GenyScraper)"},
        )
        # Cache en mémoire pour les entités (jockey, entraineur, cheval)
        self._entity_cache = {}
        self._rate_limiter = asyncio.Semaphore(1)  # 1 requête à la fois vers geny.com
        logger.info("GenyProvider initialized.")

    async def _fetch_page(self, url: str) -> str | None:
        """Effectue un appel HTTP pour récupérer une page."""
        async with self._rate_limiter:
            try:
                await asyncio.sleep(1)  # Respectful delay
                response = await self._client.get(url)
                response.raise_for_status()
                return response.text
            except httpx.RequestError as e:
                logger.error(f"GenyProvider request error for {e.request.url}: {e}")
        return None

    def _parse_stats_from_html(self, html_content: str) -> RunnerStats:
        """
        Extrait les statistiques depuis le contenu HTML d'une page entité (cheval, jockey, etc.).
        La logique de parsing est spécifique à la structure de Geny.com.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        stats = {}

        # Exemple de recherche de statistiques.
        # NOTE: Les sélecteurs sont hypothétiques et doivent être validés.
        try:
            # Recherche d'un tableau de statistiques
            stats_table = soup.find("table", class_="table-statistiques-detaillees")
            if stats_table:
                for row in stats_table.find_all("tr"):
                    cells = row.find_all("td")
                    if len(cells) < 2:
                        continue

                    label = cells[0].get_text(strip=True).lower()
                    value = cells[1].get_text(strip=True)


                    # Taux de réussite Jockey/Driver
                    if "% vict." in label: # Corrected parsing condition
                        rate_match = re.search(r"(\d[\d,.]*)", value)
                        if rate_match:
                            stats["driver_rate"] = float(rate_match.group(1).replace(",", ".")) / 100.0

                    # Taux de réussite Entraîneur
                    # Cette section sera traitée par une détection spécifique d'une page entraîneur si implémenté.
                    # Pour l'instant, le test ne couvre que le jockey.

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
        # trainer_name is not used yet

        # Pour le moment, on se concentre sur le jockey
        entity_name = jockey_name
        if not entity_name:
            return RunnerStats()

        cache_key = entity_name.lower().strip()
        if cache_key in self._entity_cache:
            logger.debug(f"Cache hit for Geny stats for: {entity_name}")
            return self._entity_cache[cache_key]

        logger.info(f"Fetching Geny stats for: {entity_name}")

        # Hypothèse: l'URL est constructible à partir du nom.
        # En réalité, une recherche serait nécessaire.
        # e.g., https://www.geny.com/jockey/y-lebourgeois_c518
        entity_slug = re.sub(r'[^\w\s-]', '', entity_name).lower().replace(" ", "-") # Corrected slug generation
        # On suppose que "jockey" est le type d'entité, à affiner
        entity_url = f"/jockey/{entity_slug}"

        html_content = await self._fetch_page(entity_url)
        if not html_content:
            logger.warning(f"Impossible de récupérer la page pour {entity_name} sur Geny.")
            return RunnerStats()

        entity_stats = self._parse_stats_from_html(html_content)

        # Mettre en cache le résultat
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

