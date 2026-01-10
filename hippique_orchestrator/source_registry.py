from __future__ import annotations

import logging
from typing import Any

from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.sources.boturfers_provider import BoturfersProvider
from hippique_orchestrator.sources.france_galop_provider import FranceGalopProvider
from hippique_orchestrator.sources.letrot_provider import LeTrotProvider
from hippique_orchestrator.sources.zeturf_provider import ZeturfProvider
from hippique_orchestrator.sources.zoneturf_chrono_provider import ZoneTurfChronoProvider

logger = get_logger(__name__)


class SourceRegistry:
    """
    Manages and provides access to different data source providers based on a defined strategy.
    """

    def __init__(self):
        self._boturfers = BoturfersProvider()
        self._zeturf = ZeturfProvider()
        self._letrot = LeTrotProvider()
        self._france_galop = FranceGalopProvider()
        self._zoneturf_chrono = ZoneTurfChronoProvider()
        logger.info("SourceRegistry initialized with available providers.")

    async def fetch_programme(
        self, url: str, correlation_id: str | None = None, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Fetches the daily race programme.
        Strategy: Always use Boturfers (primary PMU source).
        """
        logger.info(
            "Fetching programme using BoturfersProvider.",
            extra={"url": url, "correlation_id": correlation_id},
        )
        return await self._boturfers.fetch_programme(
            url, correlation_id=correlation_id, trace_id=trace_id
        )

    async def fetch_snapshot(
        self,
        race_url: str,
        *,
        phase: str = "H30",
        date: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetches a detailed race snapshot.
        Strategy: Use Boturfers first, fallback to ZEturf if quality insufficient or error.
        """
        logger.info(
            "Attempting to fetch snapshot using BoturfersProvider.",
            extra={"url": race_url, "phase": phase, "correlation_id": correlation_id},
        )
        try:
            boturfers_snapshot = await self._boturfers.fetch_snapshot(
                race_url, phase=phase, date=date, correlation_id=correlation_id, trace_id=trace_id
            )
            # Implement quality check logic here later based on schema
            # For now, a simple check if runners are present
            if boturfers_snapshot and boturfers_snapshot.get("runners"):
                logger.info(
                    "Snapshot successfully fetched from BoturfersProvider.",
                    extra={"url": race_url, "phase": phase, "correlation_id": correlation_id},
                )
                return boturfers_snapshot
        except Exception as e:
            logger.warning(
                f"BoturfersProvider failed to fetch snapshot for {race_url}: {e}. Attempting ZeturfProvider fallback.",
                exc_info=True,
                extra={"url": race_url, "phase": phase, "correlation_id": correlation_id},
            )

        logger.info(
            "Attempting to fetch snapshot using ZeturfProvider (fallback).",
            extra={"url": race_url, "phase": phase, "correlation_id": correlation_id},
        )
        return await self._zeturf.fetch_snapshot(
            race_url, phase=phase, date=date, correlation_id=correlation_id, trace_id=trace_id
        )

    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: dict[str, Any],
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetches statistics for a specific runner.
        Strategy:
        - Discipline Trot: LeTrotProvider (for jockey/trainer stats) and ZoneTurfChronoProvider (for chrono stats)
        - Discipline Galop/Obstacle: FranceGalopProvider (for jockey/trainer stats) and ZoneTurfChronoProvider (for chrono stats)
        """
        all_stats: dict[str, Any] = {}
        discipline_lower = discipline.lower()

        # Fetch chrono stats regardless of discipline (using ZoneTurf as the generic chrono source)
        logger.info(
            f"Fetching chrono stats for {runner_name} using ZoneTurfChronoProvider.",
            extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
        )
        chrono_stats = await self._zoneturf_chrono.fetch_stats_for_runner(
            runner_name, discipline, runner_data, correlation_id, trace_id
        )
        all_stats.update(chrono_stats)


        if "trot" in discipline_lower:
            logger.info(
                f"Fetching trot stats for {runner_name} using LeTrotProvider.",
                extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
            )
            provider_stats = await self._letrot.fetch_stats_for_runner(
                runner_name, discipline, runner_data, correlation_id, trace_id
            )
            all_stats.update(provider_stats)
        elif discipline_lower in ["galop", "obstacle", "plat", "steeple", "haies", "cross"]:
            logger.info(
                f"Fetching galop/obstacle stats for {runner_name} using FranceGalopProvider.",
                extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
            )
            provider_stats = await self._france_galop.fetch_stats_for_runner(
                runner_name, discipline, runner_data, correlation_id, trace_id
            )
            all_stats.update(provider_stats)
        else:
            logger.warning(
                f"No specific stats provider for discipline: {discipline}. Returning only chrono stats.",
                extra={"runner_name": runner_name, "discipline": discipline, "correlation_id": correlation_id},
            )
        
        return all_stats

    def _get_provider(self, name: str):
        """Internal method to get a provider instance by name."""
        if name == "boturfers":
            return self._boturfers
        if name == "zeturf":
            return self._zeturf
        if name == "letrot":
            return self._letrot
        if name == "france_galop":
            return self._france_galop
        if name == "zoneturf_chrono":
            return self._zoneturf_chrono
        raise ValueError(f"Unknown provider: {name}")

# Create a singleton instance
source_registry = SourceRegistry()
