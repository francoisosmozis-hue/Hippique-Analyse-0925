# hippique_orchestrator/providers/base.py
"""
Defines the abstract interface for all data providers.
"""
from abc import ABC, abstractmethod
from datetime import date
from typing import List, Tuple, Optional, Dict

from hippique_orchestrator.contracts.models import Race, Runner, OddsSnapshot, Meeting

class Provider(ABC):
    """
    Abstract Base Class for any data provider.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """The unique name of this provider, e.g., 'Boturfers-Live'."""
        pass

    @abstractmethod
    def fetch_programme(self, for_date: date) -> List[Race]:
        """
        Fetches all races for a given date.
        """
        pass

    @abstractmethod
    def fetch_race_details(self, race: Race, phase: str) -> Tuple[List[Runner], OddsSnapshot]:
        """
        Fetches the detailed runners list and odds for a specific race and phase.
        Returns a tuple of (runners, odds_snapshot).
        """
        pass