# hippique_orchestrator/providers/base.py

from abc import ABC, abstractmethod
from datetime import date
from typing import List, Dict, Any

from hippique_orchestrator.data_contract import RaceData


class AbstractProvider(ABC):
    """
    Abstract base class for all data providers.

    It defines the contract that concrete providers must implement to fetch
    race programs and runner details.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Returns the unique name of the provider (e.g., 'boturfers', 'filesystem').
        """
        raise NotImplementedError

    @abstractmethod
    def get_races_for_date(self, for_date: date) -> List[RaceData]:
        """
        Fetches the list of races for a given date.

        Args:
            for_date: The date for which to fetch the races.

        Returns:
            A list of Race objects, compliant with the data contract.
            Returns an empty list if no races are found or if an error occurs.
        """
        raise NotImplementedError

    @abstractmethod
    def get_race_details(self, race: RaceData) -> Dict[str, Any]:
        """
        Fetches detailed information for a single race, including runners.

        Args:
            race: The Race object for which to fetch details.

        Returns:
            A dictionary containing detailed race information.
            The structure should be compliant with extended data needs.
            Returns an empty dictionary if details cannot be fetched.
        """
        raise NotImplementedError

    def health_check(self) -> bool:
        """
        Performs a simple health check to verify the provider's availability.
        Default implementation always returns True.
        Concrete providers should override this for more specific checks.

        Returns:
            True if the provider is healthy, False otherwise.
        """
        return True
