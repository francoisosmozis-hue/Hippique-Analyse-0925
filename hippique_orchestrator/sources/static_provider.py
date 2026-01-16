"""
hippique_orchestrator/sources/static_provider.py - Provider de données statiques.
"""
import datetime
import json
import logging
from pathlib import Path

from hippique_orchestrator.data_contract import RaceData, RunnerData
from hippique_orchestrator.sources.interfaces import DataSourceInterface

logger = logging.getLogger(__name__)

class StaticProvider(DataSourceInterface):
    """
    Provider de données qui lit des snapshots depuis des fichiers locaux.
    Utilisé principalement pour les tests et la CI.
    """

    def __init__(self, snapshot_path: str = "data/ci_sample/sample_snapshot.json"):
        self._snapshot_path = Path(snapshot_path)
        self._snapshot = None

    def _load_snapshot(self):
        """Charge le snapshot depuis le fichier s'il n'est pas déjà chargé."""
        if self._snapshot:
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
        return "StaticProvider"

    async def get_races_for_date(self, target_date: datetime.date) -> list[RaceData]:
        """
        Retourne la course du snapshot si la date correspond.
        """
        self._load_snapshot()
        if not self._snapshot or "race" not in self._snapshot:
            return []

        race_data_dict = self._snapshot["race"]
        race_date = datetime.datetime.fromisoformat(race_data_dict["date"]).date()

        if race_date == target_date:
            return [RaceData(**race_data_dict)]

        return []

    async def get_runners_for_race(self, race: RaceData) -> list[RunnerData]:
        """
        Retourne les partants du snapshot si l'URL de la course correspond.
        """
        self._load_snapshot()
        if not self._snapshot or "runners" not in self._snapshot or "race" not in self._snapshot:
            return []

        snapshot_race_url = self._snapshot["race"].get("url")
        if race.url and snapshot_race_url == race.url:
            runners_data = self._snapshot["runners"]
            return [RunnerData(**runner) for runner in runners_data]

        return []
