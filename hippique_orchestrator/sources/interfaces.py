"""
hippique_orchestrator/sources/interfaces.py - Interfaces pour les sources de données.
"""
from abc import ABC, abstractmethod
import datetime

from hippique_orchestrator.data_contract import RaceData, RunnerData


class DataSourceInterface(ABC):
    """
    Interface abstraite pour une source de données.

    Une source de données peut être un scraper live, un lecteur de fichiers statiques,
    ou un client de base de données. Elle est responsable de fournir des données
    conformes au `data_contract`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Retourne le nom de la source de données (ex: 'Boturfers', 'StaticProvider')."""
        pass

    @abstractmethod
    async def get_races_for_date(self, target_date: datetime.date) -> list[RaceData]:
        """
        Récupère la liste des courses pour une date donnée.

        Chaque course doit contenir assez d'informations pour être identifiée de manière unique,
        notamment une URL.
        """
        pass

    @abstractmethod
    async def get_runners_for_race(self, race: RaceData) -> list[RunnerData]:
        """
        Récupère la liste des partants (avec cotes, stats, etc.) pour une course.

        La course est identifiée par l'objet RaceData obtenu via `get_races_for_date`.
        L'implémentation utilisera typiquement l'URL contenue dans `race.url`.
        """
        pass
