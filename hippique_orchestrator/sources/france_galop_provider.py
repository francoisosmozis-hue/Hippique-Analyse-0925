from __future__ import annotations

import logging
from typing import Any

from hippique_orchestrator.sources_interfaces import SourceProvider
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)


class FranceGalopProvider(SourceProvider):
    """
    Provides statistics for Galop and Obstacle disciplines from France-Galop.com.
    (Currently returns dummy data as actual scraping logic needs to be implemented).
    """

    def __init__(self):
        logger.info("FranceGalopProvider initialized.")

    async def fetch_programme(
        self, url: str, correlation_id: str | None = None, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        logger.info(
            "FranceGalopProvider does not implement programme fetching. Returning empty list.",
            extra={"url": url, "correlation_id": correlation_id},
        )
        return []

    async def fetch_snapshot(
        self,
        race_url: str,
        *,
        phase: str = "H30",
        date: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "FranceGalopProvider does not implement snapshot fetching. Returning empty dict.",
            extra={"url": race_url, "correlation_id": correlation_id},
        )
        return {}

    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict[str, Any],
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetches statistics for a specific runner for Galop/Obstacle disciplines from France-Galop.com.
        (Currently returns dummy data as actual scraping logic needs to be implemented).
        """
        if discipline.lower() not in ["galop", "obstacle", "plat", "steeple", "haies", "cross"]:
            logger.warning(
                f"FranceGalopProvider called for non-galop/obstacle discipline: {discipline}. Returning empty stats.",
                extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
            )
            return {}
        
        # Dummy implementation: In a real scenario, this would involve scraping France-Galop.com
        # for jockey, trainer, and horse stats relevant to galop/obstacle races.
        logger.info(
            f"Fetching dummy galop/obstacle stats for runner: {runner_name} (Discipline: {discipline})",
            extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
        )
        return {
            "jockey_galop_rate": 0.28, # Example dummy stat
            "trainer_galop_rate": 0.32, # Example dummy stat
            "horse_galop_form_score": 8.1, # Example dummy stat
            "source": "FranceGalop",
        }