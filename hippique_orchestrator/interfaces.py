# hippique_orchestrator/interfaces.py
"""
Defines the abstract interfaces for key components of the orchestrator,
such as data providers (scrapers).
"""
from abc import ABC, abstractmethod
from datetime import date
from typing import List, Tuple, Optional

from hippique_orchestrator.data_contract import Race, Runner, OddsSnapshot, Meeting


class ProgrammeProvider(ABC):
    """
    Abstract Base Class for any data provider that can fetch race programs and details.
    Implementations of this class are responsible for scraping or connecting to APIs.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """The unique name of this provider, e.g., 'Boturfers'."""
        pass

    @abstractmethod
    def fetch_programme(self, for_date: date) -> Tuple[List[Meeting], List[Race]]:
        """
        Fetches all meetings and races for a given date.

        Args:
            for_date: The date for which to fetch the program.

        Returns:
            A tuple containing a list of Meeting objects and a list of Race objects.
            Races must contain a valid `meeting_ref`.
        """
        pass

    @abstractmethod
    def fetch_race_details(self, race: Race, phase: str) -> Tuple[List[Runner], OddsSnapshot]:
        """
        Fetches the detailed runners list and odds for a specific race and phase.

        Args:
            race: The Race object (containing stable UIDs) to fetch details for.
            phase: The analysis phase, e.g., 'H30', 'H5'.

        Returns:
            A tuple containing:
            - A list of Runner objects for that race.
            - An OddsSnapshot object with the odds for the given phase.
        """
        pass
