"""
Fournit une stratégie multi-sources pour récupérer le programme des courses
en s'appuyant sur la résilience du source_registry.
"""
import datetime
import logging
from typing import Any

from hippique_orchestrator.source_registry import AllSourcesFailedError, source_registry

logger = logging.getLogger(__name__)


class ProgrammeProvider:
    """
    Orchestre la récupération du programme en déléguant la logique de fallback
    au `source_registry`. Construit l'URL du programme pour une date donnée.
    """

    def __init__(self, registry, base_programme_url: str = "https://www.boturfers.fr/courses"):
        """
        Initialise le provider avec le registre de sources.

        :param registry: L'instance de SourceRegistry.
        :param base_programme_url: L'URL de base pour le programme (devrait venir d'une config).
        """
        self.registry = registry
        self.base_programme_url = base_programme_url
        logger.info("ProgrammeProvider initialized.")

    async def get_races_for_date(self, target_date: datetime.date) -> list[dict[str, Any]]:
        """
        Récupère le programme pour une date en appelant le mécanisme de
        fallback du source_registry.
        """
        # La construction de l'URL est la responsabilité de ce provider.
        # Le format exact dépend de la source primaire (ex: Boturfers).
        url = f"{self.base_programme_url}/{target_date.strftime('%Y-%m-%d')}"
        logger.info(f"Requesting programme for date {target_date} via registry (URL: {url})")

        try:
            # On délègue toute la complexité (fetch, validation, fallback) au registre.
            programme = await self.registry.fetch_programme_with_fallback(url)
            logger.info(
                f"Programme ({len(programme)} courses) retrieved successfully via source_registry."
            )
            return programme
        except AllSourcesFailedError as e:
            logger.critical(
                f"All sources failed to provide the programme for {target_date}: {e}"
            )
            return []


# Instance unique pour être utilisée dans l'application.
# La configuration (ordre des providers, URL) se fait au démarrage de l'app.
programme_provider = ProgrammeProvider(source_registry)