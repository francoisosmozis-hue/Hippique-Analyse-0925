from __future__ import annotations
import logging
from typing import Any

from hippique_orchestrator.sources.interfaces import DataSourceInterface

logger = logging.getLogger(__name__)


class SourceRegistry:
    """
    Manage and provide access to different data source providers.
    """

    def __init__(self):
        self._providers: dict[str, DataSourceInterface] = {}
        logger.info("SourceRegistry initialized.")

    def register(self, provider: DataSourceInterface, overwrite: bool = False):
        """Registers a data source provider."""
        if provider.name in self._providers and not overwrite:
            logger.warning(
                f"Provider '{provider.name}' is already registered. Use overwrite=True to replace it."
            )
            return

        logger.info(f"Registering provider: {provider.name}")
        self._providers[provider.name] = provider

    def get_provider(self, name: str) -> DataSourceInterface | None:
        """Gets a provider by name."""
        provider = self._providers.get(name)
        if not provider:
            logger.error(f"Provider '{name}' not found in registry.")
        return provider

    def get_all_providers(self) -> list[DataSourceInterface]:
        """Gets a list of all registered providers."""
        return list(self._providers.values())


# Create a singleton instance
source_registry = SourceRegistry()