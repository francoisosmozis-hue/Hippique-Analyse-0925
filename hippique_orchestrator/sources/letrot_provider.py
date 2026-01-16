from __future__ import annotations

import asyncio
import re
from typing import Any
import random

import httpx
from bs4 import BeautifulSoup

from hippique_orchestrator.data_contract import RunnerStats
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.sources_interfaces import SourceProvider
from hippique_orchestrator.utils.retry import (
    async_http_retry,
    check_for_antibot,
    check_for_retriable_status,
)
from hippique_orchestrator import config

logger = get_logger(__name__)


class LeTrotProvider(SourceProvider):
    """
    Fournit des statistiques réelles pour la discipline du Trot depuis LeTrot.com.
    Cette implémentation simule le scraping pour être testable et montrer la logique.
    """

    name = "LeTrot"
    BASE_URL = "https://www.letrot.com"

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=config.TIMEOUT_S,
            headers={"User-Agent": "HippiqueOrchestrator/1.0"},
            follow_redirects=True,
        )
        self._runner_cache = {}
        self._rate_limiter = asyncio.Semaphore(1)
        logger.info("LeTrotProvider initialized with real scraping logic.")

    @async_http_retry
    async def _fetch_page(self, url: str) -> str:
        """Effectue un appel HTTP respectueux pour récupérer une page."""
        async with self._rate_limiter:
            await asyncio.sleep(random.uniform(0.5, 1.5))  # Be respectful
            response = await self._client.get(url)
            
            check_for_retriable_status(response)
            response.raise_for_status()

            html_content = response.text
            check_for_antibot(html_content)
            
            return html_content

    def _parse_runner_stats_from_html(self, html_content: str, runner_name: str) -> RunnerStats:
        """
        Extrait les statistiques d'un coureur depuis le contenu HTML de sa page.
        C'est ici que la logique de parsing spécifique à LeTrot doit être implémentée.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        stats = {}

        # Exemple: trouver le tableau des performances et extraire les taux de réussite
        # NOTE: Les sélecteurs CSS sont des exemples et doivent être adaptés à la structure réelle de LeTrot.
        try:
            # Taux de réussite driver/jockey
            driver_stats_table = soup.select_one("#page-fiche-personne .table-performances-driver")
            if driver_stats_table:
                # Cherche la ligne "Victoires" et le % associé
                victoires_row = driver_stats_table.find("td", string=re.compile(r"Victoires"))
                if victoires_row and (rate_cell := victoires_row.find_next_sibling("td")):
                    rate_match = re.search(r"(\d{1,2})%", rate_cell.text)
                    if rate_match:
                        stats["driver_rate"] = float(rate_match.group(1)) / 100.0

            # Taux de réussite entraîneur
            trainer_stats_table = soup.select_one("#page-fiche-personne .table-performances-entraineur")
            if trainer_stats_table:
                victoires_row = trainer_stats_table.find("td", string=re.compile(r"Victoires"))
                if victoires_row and (rate_cell := victoires_row.find_next_sibling("td")):
                    rate_match = re.search(r"(\d{1,2})%", rate_cell.text)
                    if rate_match:
                        stats["trainer_rate"] = float(rate_match.group(1)) / 100.0

            logger.info(f"Stats parsées pour {runner_name}: {stats}")

        except Exception as e:
            logger.error(f"Erreur lors du parsing des stats pour {runner_name}: {e}")

        return RunnerStats(
            driver_rate=stats.get("driver_rate"),
            trainer_rate=stats.get("trainer_rate"),
            source_stats="LeTrot",
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
        Orchestre la récupération des statistiques pour un coureur.
        Utilise un cache pour éviter les appels répétés.
        """
        if "trot" not in discipline.lower():
            return RunnerStats()

        cache_key = runner_name.lower().strip()
        if cache_key in self._runner_cache:
            logger.debug(f"Cache hit for LeTrot stats for runner: {runner_name}")
            return self._runner_cache[cache_key]

        logger.info(f"Fetching LeTrot stats for runner: {runner_name}")

        runner_url = f"/fiche-personne/{runner_name.lower().replace(' ', '-')}"

        try:
            html_content = await self._fetch_page(runner_url)
        except Exception as e:
            logger.critical(
                f"Échec final de la récupération de la page pour {runner_name} sur LeTrot: {e}",
                exc_info=True
            )
            return RunnerStats()

        if not html_content:
            logger.warning(f"Aucun contenu HTML pour {runner_name} sur LeTrot après les tentatives.")
            return RunnerStats()
        
        runner_stats = self._parse_runner_stats_from_html(html_content, runner_name)

        if runner_stats.driver_rate or runner_stats.trainer_rate:
            self._runner_cache[cache_key] = runner_stats

        return runner_stats

    # Les autres méthodes ne sont pas implémentées car ce provider est spécialisé en stats
    async def fetch_programme(self, *args, **kwargs) -> list[dict[str, Any]]:
        return []

    async def fetch_snapshot(self, *args, **kwargs) -> dict[str, Any]:
        return {}
