from typing import Dict, Any, List
from hippique_orchestrator.providers.base_provider import BaseProgrammeProvider, BaseSnapshotProvider

class MockProvider(BaseProgrammeProvider, BaseSnapshotProvider):
    """
    A mock provider for testing and demonstration purposes.
    It returns hardcoded data and does not make any external calls.
    """
    def __init__(self):
        """Initializes the mock provider. No config needed."""
        pass

    def get_programme(self, date: str) -> List[Dict[str, Any]]:
        """
        Returns a mock race programme for the given date.
        """
        print(f"MockProvider: Fetching programme for {date}...")
        return [
            {
                "meeting_id": "R1",
                "race_id": "C1",
                "course_id": f"{date}_R1C1",
                "race_name": "Prix d'Essai",
                "start_time": "13:50"
            },
            {
                "meeting_id": "R1",
                "race_id": "C2",
                "course_id": f"{date}_R1C2",
                "race_name": "Grand Prix",
                "start_time": "14:25"
            }
        ]

    def fetch_snapshot(self, meeting_id: str, race_id: str, course_id: str) -> str:
        """
        Returns a mock raw snapshot for the given race.
        """
        print(f"MockProvider: Fetching snapshot for {course_id} ({meeting_id}/{race_id})...")
        return f"<html><body>Mock snapshot for {course_id}</body></html>"

    def parse_snapshot(self, snapshot_content: str) -> Dict[str, Any]:
        """
        Parses the mock snapshot content.
        """
        print(f"MockProvider: Parsing snapshot content: '{snapshot_content}'...")
        return {
            "metadata": {
                "source": "mock",
                "content": snapshot_content
            },
            "runners": [
                {"name": "Cheval Un", "odds": "5.0"},
                {"name": "Cheval Deux", "odds": "3.5"},
            ]
        }