"""
Fournit une stratégie multi-sources pour récupérer le programme des courses.
"""
import asyncio
import datetime
import logging
from abc import ABC, abstractmethod
from typing import Any

from hippique_orchestrator.source_registry import source_registry

logger = logging.getLogger(__name__)


class BaseProgrammeProvider(ABC):
    """Classe de base abstraite pour un fournisseur de programme."""
    def __init__(self, registry):
        self.source_registry = registry

    @abstractmethod
    async def get_programme(self, target_date: datetime.date) -> list[dict[str, Any]]:
        """
        Récupère le programme pour une date donnée.
        Doit retourner une liste de dictionnaires, chacun représentant une course.
        """
        pass

    @property
    def name(self):
        return self.__class__.__name__


class BoturfersProgrammeProvider(BaseProgrammeProvider):
    """Récupère le programme depuis Boturfers (aujourd'hui/demain uniquement)."""
    async def get_programme(self, target_date: datetime.date) -> list[dict[str, Any]]:
        today = datetime.datetime.now(datetime.timezone.utc).date()
        tomorrow = today + datetime.timedelta(days=1)

        url = None
        if target_date == today:
            url = "https://www.boturfers.fr/programme-pmu-du-jour"
        elif target_date == tomorrow:
            url = "https://www.boturfers.fr/programme-pmu-demain"

        if not url:
            logger.debug(f"{self.name} ne supporte pas la date {target_date}.")
            return []

        logger.info(f"[{self.name}] Récupération du programme depuis {url}")
        # On suppose que la source_registry a une méthode pour ça
        programme = await self.source_registry.fetch_programme(url)
        if programme:
            logger.info(f"[{self.name}] {len(programme)} courses trouvées.")
        return programme


class PmuProgrammeProvider(BaseProgrammeProvider):
    """
    Récupère le programme depuis PMU.fr. (STUB)
    C'est la cible prioritaire.
    """
    async def get_programme(self, target_date: datetime.date) -> list[dict[str, Any]]:
        logger.info(f"[{self.name}] Tentative de récupération pour le {target_date.isoformat()} (implémentation factice).")
        # TODO: Implémenter le scraping de PMU, potentiellement via une API "privée"
        # découverte en analysant le trafic réseau du site.
        # Exemple d'URL à analyser : https://www.pmu.fr/turf/{target_date.strftime('%d%m%Y')}
        await asyncio.sleep(0.1) # Simule un appel réseau
        return []


class GenyProgrammeProvider(BaseProgrammeProvider):
    """
    Récupère le programme depuis Geny.com. (STUB)
    Bonne source de fallback.
    """
    async def get_programme(self, target_date: datetime.date) -> list[dict[str, Any]]:
        logger.info(f"[{self.name}] Tentative de récupération pour le {target_date.isoformat()} (implémentation factice).")
        # TODO: Implémenter le scraping de Geny.
        await asyncio.sleep(0.1) # Simule un appel réseau
        return []


class ProgrammeProvider:
    """
    Orchestre la récupération du programme en essayant plusieurs sources
    dans un ordre de priorité défini.
    """
    def __init__(self, registry):
        self.providers = [
            PmuProgrammeProvider(registry),
            GenyProgrammeProvider(registry),
            BoturfersProgrammeProvider(registry),  # En dernier recours
        ]

    async def get_programme(self, target_date: datetime.date) -> list[dict[str, Any]]:
        """
        Essaie chaque provider jusqu'à obtenir un programme non vide.
        """
        for provider in self.providers:
            try:
                logger.info(f"Tentative avec le provider de programme: {provider.name}")
                programme = await provider.get_programme(target_date)
                if programme:
                    logger.info(f"Programme obtenu avec succès via {provider.name} ({len(programme)} courses).")
                    return programme
            except Exception as e:
                logger.error(f"Le provider de programme {provider.name} a échoué: {e}", exc_info=True)

        logger.warning("Aucun provider de programme n'a pu fournir de plan.")
        return []

# Instance unique pour être utilisée dans l'application
programme_provider = ProgrammeProvider(source_registry)
