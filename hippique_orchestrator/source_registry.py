from __future__ import annotations

import asyncio
from typing import Any

from hippique_orchestrator.data_contract import (
    RaceSnapshotNormalized,
    RunnerStats,
    calculate_quality_score,
)
from hippique_orchestrator.logging_utils import get_logger
from hippique_orchestrator.sources.boturfers_provider import BoturfersProvider
from hippique_orchestrator.sources.france_galop_provider import FranceGalopProvider
from hippique_orchestrator.sources.geny_provider import GenyProvider  # Added import
from hippique_orchestrator.sources.letrot_provider import LeTrotProvider
from hippique_orchestrator.sources.zeturf_provider import ZeturfProvider
from hippique_orchestrator.sources.zoneturf_chrono_provider import ZoneTurfChronoProvider

logger = get_logger(__name__)


class SourceRegistry:
    """
    Manage and provide access to different data source providers, including fallback
    strategies and data enrichment.
    """

    def __init__(self):
        # Snapshot providers
        self._primary_snapshot_provider = ZeturfProvider()
        self._fallback_snapshot_provider = BoturfersProvider()

        # Stats providers
        self._letrot = LeTrotProvider()
        self._france_galop = FranceGalopProvider()
        self._zoneturf_chrono = ZoneTurfChronoProvider()
        self._geny = GenyProvider() # Added GenyProvider
        logger.info("SourceRegistry initialized with primary and fallback providers.")

    async def fetch_programme(
        self, url: str, correlation_id: str | None = None, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Fetches the daily race programme.
        NOTE: This method is now legacy, as programme fetching is handled by ProgrammeProvider.
        It's kept for compatibility until all calls are migrated.
        """
        logger.warning("Legacy fetch_programme called. Please use ProgrammeProvider instead.")
        return await self._fallback_snapshot_provider.fetch_programme(
            url, correlation_id=correlation_id, trace_id=trace_id
        )

    async def get_snapshot(
        self,
        race_url: str,
        *,
        phase: str = "H30",
        date: str | None = None,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> RaceSnapshotNormalized | None:
        """
        Fetches a race snapshot using a primary provider and falls back to another
        if the data quality is insufficient.
        It then enriches the best available snapshot with stats.
        """
        primary_provider = self._primary_snapshot_provider
        fallback_provider = self._fallback_snapshot_provider

        logger.info(f"Attempting snapshot with primary provider: {primary_provider.name}")
        snapshot = None
        try:
            snapshot = await primary_provider.fetch_snapshot(
                race_url, phase=phase, date=date, correlation_id=correlation_id, trace_id=trace_id
            )
            quality = calculate_quality_score(snapshot)
            logger.info(f"Primary snapshot quality: {quality['status']} ({quality['score']})")

            if quality["status"] == "FAILED":
                logger.warning("Primary snapshot failed quality check, attempting fallback.")
                snapshot = None # Force fallback

        except Exception as e:
            logger.error(f"Primary provider {primary_provider.name} failed: {e}", exc_info=True)
            snapshot = None

        if snapshot is None:
            logger.info(f"Attempting snapshot with fallback provider: {fallback_provider.name}")
            try:
                snapshot = await fallback_provider.fetch_snapshot(
                    race_url, phase=phase, date=date, correlation_id=correlation_id, trace_id=trace_id
                )
            except Exception as e:
                logger.critical(f"All snapshot providers failed for {race_url}: {e}", exc_info=True)
                return None

        if snapshot:
            logger.info("Snapshot obtained, proceeding to stats enrichment.")
            snapshot = await self.enrich_snapshot_with_stats(
                snapshot, correlation_id=correlation_id, trace_id=trace_id
            )

        return snapshot

    async def enrich_snapshot_with_stats(
        self,
        snapshot: RaceSnapshotNormalized,
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> RaceSnapshotNormalized:
        """
        Enriches a snapshot with statistics for each runner based on discipline.
        """
        discipline = snapshot.race.discipline or ""
        discipline_lower = discipline.lower()

        stats_tasks = []
        for runner in snapshot.runners:
            # The name of the runner is needed to fetch stats
            runner_name = runner.name
            # Existing runner data can be useful context for some providers
            runner_data_dict = runner.model_dump()
            stats_tasks.append(
                self._fetch_stats_for_runner_task(
                    runner_name, discipline_lower, runner_data_dict, correlation_id, trace_id
                )
            )

        all_runners_stats: list[RunnerStats] = await asyncio.gather(*stats_tasks)

        for i, runner_stats in enumerate(all_runners_stats):
            snapshot.runners[i].stats = runner_stats

        return snapshot

    async def _fetch_stats_for_runner_task(
        self,
        runner_name: str,
        discipline_lower: str,
        runner_data: dict[str, Any],
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> RunnerStats:
        """
        Fetches all relevant stats for a single runner. This is a helper for asyncio.gather.
        It uses a fallback strategy if the primary stats provider returns no data.
        """
        stats = RunnerStats()

        # Primary stats provider based on discipline
        if "trot" in discipline_lower:
            stats = await self._letrot.fetch_stats_for_runner(
                runner_name=runner_name,
                discipline=discipline_lower,
                runner_data=runner_data,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )
        elif "galop" in discipline_lower or "plat" in discipline_lower or "obstacle" in discipline_lower:
            stats = await self._france_galop.fetch_stats_for_runner(
                runner_name=runner_name,
                discipline=discipline_lower,
                runner_data=runner_data,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )

        # Fallback to Geny if no stats were found from the primary provider
        if not stats.driver_rate and not stats.trainer_rate:
            logger.info(f"No stats from primary provider for {runner_name}, trying Geny as fallback.")
            geny_stats = await self._geny.fetch_stats_for_runner(
                runner_name=runner_name,
                discipline=discipline_lower,
                runner_data=runner_data,
                correlation_id=correlation_id,
                trace_id=trace_id,
            )
            # Merge Geny stats if any are found
            if geny_stats.driver_rate or geny_stats.trainer_rate:
                stats = geny_stats

        # --- Chrono stats ---
        # ZoneTurf is a good source for chronos, call it regardless of discipline.
        chrono_stats = await self._zoneturf_chrono.fetch_stats_for_runner(
            runner_name=runner_name,
            discipline=discipline_lower,
            runner_data=runner_data,
            correlation_id=correlation_id,
            trace_id=trace_id,
        )
        if chrono_stats.best_chrono:
            stats.best_chrono = chrono_stats.best_chrono
        if chrono_stats.previous_chronos:
            stats.previous_chronos = chrono_stats.previous_chronos

        return stats


# Create a singleton instance
source_registry = SourceRegistry()
