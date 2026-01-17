from abc import ABC, abstractmethod
from typing import Dict, Any, List

class BaseProgrammeProvider(ABC):
    """
    Abstract base class for providers that fetch the race programme for a given day.
    """
    @abstractmethod
    def get_programme(self, date: str) -> List[Dict[str, Any]]:
        """
        Fetches the race programme for a specific date.

        Args:
            date (str): The date in 'YYYY-MM-DD' format.

        Returns:
            List[Dict[str, Any]]: A list of race dictionaries, where each dictionary
                                 represents a race and contains its details.
                                 Returns an empty list if no programme is found or an error occurs.
        """
        pass

class BaseSnapshotProvider(ABC):
    """
    Abstract base class for providers that fetch snapshot data for a specific race.
    """
    @abstractmethod
    def fetch_snapshot(self, meeting_id: str, race_id: str, course_id: str) -> str:
        """
        Fetches the raw snapshot data (e.g., HTML content) for a given race.

        Args:
            meeting_id (str): The meeting identifier (e.g., 'R1').
            race_id (str): The race identifier (e.g., 'C1').
            course_id (str): A unique identifier for the course.

        Returns:
            str: The raw snapshot data as a string.
                 Returns an empty string if data cannot be fetched.
        """
        pass

    @abstractmethod
    def parse_snapshot(self, snapshot_content: str) -> Dict[str, Any]:
        """
        Parses the raw snapshot data into a structured dictionary.

        Args:
            snapshot_content (str): The raw snapshot data.

        Returns:
            Dict[str, Any]: A dictionary containing structured data about the race,
                            including runners, odds, etc.
        """
        pass