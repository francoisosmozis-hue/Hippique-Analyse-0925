"""
Fournit une stratégie multi-sources pour récupérer le programme des courses.
"""
import datetime
import logging
from typing import Any

from hippique_orchestrator.data_contract import RaceData
from hippique_orchestrator.source_registry import source_registry

logger = logging.getLogger(__name__)


class ProgrammeProvider:
    """
    Orchestre la récupération du programme en essayant plusieurs sources
    enregistrées dans le `source_registry`, selon un ordre de priorité.
    """
    def __init__(self, registry, provider_priority: list[str] | None = None):
        """
        Initialise le provider avec le registre de sources.

        :param registry: L'instance de SourceRegistry.
        :param provider_priority: Liste ordonnée des noms de providers à essayer.
        """
        self.registry = registry
        # En production, on voudra peut-être une liste comme ["PMU", "Geny", "Boturfers"]
        # Pour l'instant, on se contente de ce qui est disponible.
        self.provider_priority = provider_priority or ["Boturfers", "StaticProvider"]
        logger.info(f"ProgrammeProvider initialized with provider priority: {self.provider_priority}")

    async def get_races_for_date(self, target_date: datetime.date) -> list[RaceData]:
        """
        Essaie chaque provider du registre pour obtenir le programme.
        L'ordre est défini par `provider_priority`.
        """
        for provider_name in self.provider_priority:
            provider = self.registry.get_provider(provider_name)
            if not provider:
                logger.warning(f"Le provider de programme '{provider_name}' n'est pas enregistré.")
                continue

            try:
                logger.info(f"Tentative de récupération du programme avec: {provider.name}")
                races = await provider.get_races_for_date(target_date)
                if races:
                    logger.info(f"Programme ({len(races)} courses) obtenu avec succès via {provider.name}.")
                    return races
            except Exception as e:
                logger.error(f"Le provider '{provider.name}' a échoué: {e}", exc_info=True)

        logger.warning(f"Aucun provider n'a pu fournir le programme pour la date {target_date}.")
        return []

# Instance unique pour être utilisée dans l'application
# La priorité peut être surchargée à l'initialisation de l'app.
programme_provider = ProgrammeProvider(source_registry)