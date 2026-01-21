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

    def get_programme(self, date: str) -> Dict[str, Any]:
        """
        Returns a mock race programme for the given date.
        """
        print(f"MockProvider: Fetching programme for {date}...")
        return {
            "date": date,
            "races": [
                {
                    "race_id": "C1",
                    "reunion_id": 1,
                    "course_id": 1,
                    "date": date,
                    "name": "Prix d'Essai",
                    "discipline": "Trot Attelé",
                    "start_time": "13:50",
                    "url": f"http://mock.url/{date}_R1C1",
                    "runners": [
                        {"num": 1, "nom": "Mock Horse M", "odds_win": 2.1, "odds_place": 1.1},
                        {"num": 2, "nom": "Mock Horse N", "odds_win": 4.5, "odds_place": 1.4},
                    ],
                },
                {
                    "race_id": "C2",
                    "reunion_id": 1,
                    "course_id": 2,
                    "date": date,
                    "name": "Grand Prix",
                    "discipline": "Plat",
                    "start_time": "14:25",
                    "url": f"http://mock.url/{date}_R1C2",
                    "runners": [
                        {"num": 1, "nom": "Mock Horse O", "odds_win": 3.0, "odds_place": 1.2},
                        {"num": 2, "nom": "Mock Horse P", "odds_win": 6.0, "odds_place": 1.5},
                    ],
                },
            ],
        }

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

    def fetch_stats_for_runner(
        self,
        runner_name: str,
        discipline: str,
        runner_data: Dict[str, Any],
        correlation_id: str | None = None,
        trace_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Returns mock stats for a runner.
        """
        print(f"MockProvider: Fetching stats for {runner_name} ({discipline})...")
        return {"mock_stat_key": f"value_for_{runner_name}"}

    