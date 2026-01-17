
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from hippique_orchestrator.data_contract import Race, Meeting


class ProviderInterface(ABC):
    """
    Abstract interface for a data provider.

    A provider is responsible for fetching racing data (meetings, races, runners)
    from an external source. It must also provide basic metadata about its status.
    """

    @abstractmethod
    def get_name(self) -> str:
        """Returns the unique name of the provider (e.g., 'boturfers', 'mock')."""
        pass

    @abstractmethod
    def get_races_for_date(self, date: str) -> Optional[List[Dict[str, Any]]]:
        """
        Fetches the list of races for a given date.

        Args:
            date (str): The date in 'YYYY-MM-DD' format.

        Returns:
            Optional[List[Dict[str, Any]]]: A list of race dictionaries,
                                             or None if the provider fails.
                                             The dict should conform to a subset
                                             of the Race data contract.
        """
        pass

    @abstractmethod
    def get_race_details(self, race_url: str) -> Optional[Dict[str, Any]]:
        """
        Fetches detailed information for a single race, including runners.

        Args:
            race_url (str): The unique URL or identifier for the race.

        Returns:
            Optional[Dict[str, Any]]: A dictionary containing detailed race and
                                      runner information, or None if the
                                      provider fails. This should conform to the
                                      full Race data contract.
        """
        pass

    def get_meetings_for_date(self, date: str) -> Optional[List[Meeting]]:
        """
        Fetches the list of meetings for a given date.
        This can be a default implementation that derives meetings from races.
        Providers can override it for more efficiency if their source provides
        a dedicated meeting endpoint.

        Args:
            date (str): The date in 'YYYY-MM-DD' format.

        Returns:
            Optional[List[Meeting]]: A list of Meeting objects, or None if fetching fails.
        """
        races_data = self.get_races_for_date(date)
        if races_data is None:
            return None

        meetings: Dict[str, Meeting] = {}
        for race_dict in races_data:
            race = Race(**race_dict)
            meeting_id = f"{race.hippodrome}-{race.country_code}"
            if meeting_id not in meetings:
                meetings[meeting_id] = Meeting(
                    id=meeting_id,
                    hippodrome=race.hippodrome,
                    country_code=race.country_code,
                    races_count=0,
                    races=[],
                )
            meetings[meeting_id].races_count += 1
            meetings[meeting_id].races.append(race)

        return list(meetings.values())

    @abstractmethod
    async def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: Dict[str, Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetches statistics for a specific runner.

        Args:
            runner_name (str): The name of the runner.
            discipline (str): The discipline of the race (e.g., "Trot Attelé").
            runner_data (Dict[str, Any]): The full raw runner data from the race snapshot.
            correlation_id (Optional[str]): Correlation ID for logging.
            trace_id (Optional[str]): Trace ID for logging.

        Returns:
            Dict[str, Any]: A dictionary of fetched statistics (e.g., driver_rate, trainer_rate, chrono).
                            Returns an empty dict if no stats are found or an error occurs.
        """
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        """
        Performs a quick health check on the provider's source.

        Returns:
            bool: True if the source is accessible, False otherwise.
        """
        pass

