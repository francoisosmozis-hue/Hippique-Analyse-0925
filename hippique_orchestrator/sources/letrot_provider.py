from __future__ import annotations

import logging
from typing import Any

from hippique_orchestrator.sources_interfaces import SourceProvider
from hippique_orchestrator.logging_utils import get_logger

logger = get_logger(__name__)


class LeTrotProvider(SourceProvider):
    """
    Provides statistics for Trot discipline from LeTrot.com.
    (Currently returns dummy data as actual scraping logic needs to be implemented).
    """

    def __init__(self):
        logger.info("LeTrotProvider initialized.")

    async def fetch_programme(
        self, url: str, correlation_id: str | None = None, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        logger.info(
            "LeTrotProvider does not implement programme fetching. Returning empty list.",
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
            "LeTrotProvider does not implement snapshot fetching. Returning empty dict.",
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
        Fetches statistics for a specific runner for the Trot discipline from LeTrot.com.
        (Currently returns dummy data as actual scraping logic needs to be implemented).
        """
        if discipline.lower() != "trot":
            logger.warning(
                f"LeTrotProvider called for non-trot discipline: {discipline}. Returning empty stats.",
                extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
            )
            return {}
        
        # Dummy implementation: In a real scenario, this would involve scraping LeTrot.com
        # for jockey, trainer, and horse stats relevant to trot races.
        logger.info(
            f"Fetching dummy trot stats for runner: {runner_name}",
            extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
        )
        return {
            "jockey_trot_rate": 0.35, # Example dummy stat
            "trainer_trot_rate": 0.40, # Example dummy stat
            "horse_trot_form_index": 7.5, # Example dummy stat
            "source": "LeTrot",
        }
