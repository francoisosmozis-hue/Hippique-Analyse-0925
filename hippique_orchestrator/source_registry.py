from __future__ import annotations

import logging
from typing import Any

from hippique_orchestrator.data_contract import RaceSnapshotNormalized
from hippique_orchestrator.sources_interfaces import SourceProvider


logger = logging.getLogger(__name__)


class AllSourcesFailedError(Exception):
    """Raised when all data sources fail to provide valid data."""

    pass


class SourceRegistry:
    """
    Manages data source providers with a primary/fallback mechanism.
    """

    def __init__(self):
        self._providers: dict[str, SourceProvider] = {}
        self._provider_order: list[str] = []
        logger.info("SourceRegistry initialized.")

    def set_provider_order(self, order: list[str]):
        """
        Sets the preferred order of providers (primary first, then fallbacks).
        Example: ['boturfers', 'zeturf']
        """
        logger.info(f"Setting provider order: {order}")
        self._provider_order = order

    def register(self, provider: SourceProvider, overwrite: bool = False):
        """Registers a data source provider."""
        if provider.name in self._providers and not overwrite:
            logger.warning(
                f"Provider '{provider.name}' is already registered. Use overwrite=True to replace it."
            )
            return

        logger.info(f"Registering provider: {provider.name}")
        self._providers[provider.name] = provider

    def get_provider(self, name: str) -> SourceProvider | None:
        """Gets a provider by name."""
        provider = self._providers.get(name)
        if not provider:
            logger.error(f"Provider '{name}' not found in registry.")
        return provider

    async def fetch_snapshot_with_fallback(
        self, race_url: str, **kwargs
    ) -> RaceSnapshotNormalized:
        """
        Tries to fetch a snapshot from sources in the configured order.
        It validates data quality before returning and falls back to the next source on failure.
        """
        if not self._provider_order:
            msg = "Provider order is not configured in SourceRegistry."
            logger.error(msg)
            raise AllSourcesFailedError(msg)

        last_error: Exception | None = None
        for provider_name in self._provider_order:
            provider = self.get_provider(provider_name)
            if not provider:
                logger.warning(
                    f"Provider '{provider_name}' from order list not found in registry. Skipping."
                )
                continue

            try:
                logger.info(f"Attempting snapshot fetch from source: {provider.name}")
                snapshot = await provider.fetch_snapshot(race_url, **kwargs)

                if snapshot.quality["status"] != "FAILED":
                    logger.info(f"OK | Fetched and validated snapshot from '{provider.name}'.")
                    snapshot.meta["succeeded_source"] = provider.name
                    return snapshot
                else:
                    reason = snapshot.quality["reason"]
                    logger.warning(
                        f"DEGRADED/FAILED | Source '{provider.name}' returned low quality snapshot: {reason}"
                    )
                    last_error = ValueError(f"Provider '{provider.name}' returned FAILED quality snapshot.")

            except Exception as e:
                logger.error(f"CRITICAL | Source '{provider.name}' failed to fetch snapshot: {e}", exc_info=True)
                last_error = e

        logger.critical(f"All sources failed to provide a valid snapshot for url: {race_url}")
        raise AllSourcesFailedError(f"All sources failed. Last error: {last_error}")

    async def fetch_programme_with_fallback(self, url: str, **kwargs) -> list[dict[str, Any]]:
        """
        Tries to fetch a day's programme from sources in the configured order.
        Falls back to the next source on failure.
        """
        if not self._provider_order:
            msg = "Provider order is not configured in SourceRegistry."
            logger.error(msg)
            raise AllSourcesFailedError(msg)

        last_error: Exception | None = None
        for provider_name in self._provider_order:
            provider = self.get_provider(provider_name)
            if not provider:
                logger.warning(f"Provider '{provider_name}' from order list not found in registry. Skipping.")
                continue

            try:
                logger.info(f"Attempting programme fetch from source: {provider.name}")
                programme = await provider.fetch_programme(url, **kwargs)

                if programme:  # Basic validation: is the list non-empty?
                    logger.info(f"OK | Fetched programme from '{provider.name}'.")
                    return programme
                else:
                    logger.warning(f"EMPTY | Source '{provider.name}' returned an empty programme.")
                    last_error = ValueError(f"Provider '{provider.name}' returned an empty programme.")

            except Exception as e:
                logger.error(f"CRITICAL | Source '{provider.name}' failed to fetch programme: {e}", exc_info=True)
                last_error = e

        logger.critical(f"All sources failed to provide a valid programme for url: {url}")
        raise AllSourcesFailedError(f"All sources failed. Last error: {last_error}")


# Create a singleton instance
source_registry = SourceRegistry()