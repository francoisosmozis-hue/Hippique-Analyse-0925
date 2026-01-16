import datetime
import json
import logging
from pathlib import Path
from typing import Any

from hippique_orchestrator.data_contract import RaceData, RaceSnapshotNormalized, RunnerData, RunnerStats
from hippique_orchestrator.sources_interfaces import SourceProvider # Use the correct interface

logger = logging.getLogger(__name__)

class StaticProvider(SourceProvider):
    """
    Provider de données qui lit des snapshots depuis des fichiers locaux.
    Utilisé principalement pour les tests et la CI.
    """

    def __init__(self, snapshot_path: str = "data/ci_sample/sample_snapshot.json"):
        self._snapshot_path = Path(snapshot_path)
        self._snapshot: dict[str, Any] | None = None

    def _load_snapshot(self):
        """Charge le snapshot depuis le fichier s'il n'est pas déjà chargé."""
        if self._snapshot is not None:
            return

        if not self._snapshot_path.exists():
            logger.error(f"Le fichier snapshot '{self._snapshot_path}' est introuvable.")
            self._snapshot = {}
            return

        try:
            with open(self._snapshot_path, "r", encoding="utf-8") as f:
                self._snapshot = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Erreur lors de la lecture ou du parsing de '{self._snapshot_path}': {e}")
            self._snapshot = {}

    @property
    def name(self) -> str:
        return "static" # Lowercase for consistency

    async def fetch_programme(self, url: str, **kwargs) -> list[dict[str, Any]]:
        """
        Retourne le programme du snapshot si l'URL ou la date correspond.
        Pour ce provider statique, l'URL est une indication, on se basera
        principalement sur le contenu du snapshot.
        """
        self._load_snapshot()
        if not self._snapshot or "race" not in self._snapshot:
            return []

        # Assuming the URL for the program could be generic for the day
        # or contain the date
        snapshot_race_url = self._snapshot["race"].get("url")
        snapshot_date = self._snapshot["race"].get("date")

        # Basic check if the requested URL or date roughly matches the snapshot's content
        if url and snapshot_race_url and snapshot_race_url == url:
            # Return race data as a dictionary in a list, as expected by source_registry
            return [self._snapshot["race"]]
        
        # If the URL is for a date-based program, try to match the date
        if "date" in url and snapshot_date and snapshot_date in url:
             return [self._snapshot["race"]]

        return []

    async def fetch_snapshot(self, race_url: str, **kwargs) -> RaceSnapshotNormalized:
        """
        Retourne le RaceSnapshotNormalized du snapshot si l'URL de la course correspond.
        """
        self._load_snapshot()
        if not self._snapshot:
            raise ValueError("Static snapshot not loaded or empty.")

        snapshot_race_url = self._snapshot["race"].get("url")
        if race_url and snapshot_race_url == race_url:
            # Construct RaceSnapshotNormalized from loaded snapshot data
            race_data_dict = self._snapshot["race"]
            runners_data_list = self._snapshot["runners"]
            
            # Ensure race date is a datetime.date object
            race_date = datetime.datetime.fromisoformat(race_data_dict["date"]).date()

            race_data = RaceData(
                date=race_date,
                rc_label=race_data_dict.get("rc_label", "N/A"),
                name=race_data_dict.get("name"),
                url=race_data_dict.get("url"),
                discipline=race_data_dict.get("discipline"),
                distance=race_data_dict.get("distance"),
                corde=race_data_dict.get("corde"),
                type_course=race_data_dict.get("type_course"),
                prize=race_data_dict.get("prize"),
                start_time_local=None # Assuming start_time is not in snapshot
            )

            runners = [RunnerData(**runner_dict) for runner_dict in runners_data_list]

            return RaceSnapshotNormalized(
                race=race_data,
                runners=runners,
                source_snapshot=self.name,
                meta=self._snapshot.get("meta", {})
            )
        raise ValueError(f"Race URL '{race_url}' not found in static snapshot.")

    async def fetch_stats_for_runner(self, runner_name: str, **kwargs) -> RunnerStats:
        """Static provider does not provide dynamic runner stats."""
        logger.warning(f"[{self.name}] does not provide stats. Returning empty stats object for {runner_name}.")
        return RunnerStats(source_stats=self.name)

