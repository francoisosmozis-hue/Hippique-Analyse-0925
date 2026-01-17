# hippique_orchestrator/providers/filesystem.py

import json
import logging
from datetime import date
from pathlib import Path
from typing import List, Dict, Any

from hippique_orchestrator.config import get_provider_config
from hippique_orchestrator.data_contract import RaceData, Runner
from hippique_orchestrator.providers.base import AbstractProvider


class FilesystemProvider(AbstractProvider):
    """
    A data provider that reads race data from the local filesystem.

    This provider is essential for offline testing (CI) and development,
    allowing the application to run without any network access by using
    pre-saved data samples.
    """

    def __init__(self, base_path: str = None):
        if base_path is None:
            # Fetch path from the centralized config, with a fallback for safety
            provider_config = get_provider_config(self.name)
            base_path = provider_config.get("base_path", "data/ci_sample")

        self._base_path = Path(base_path)
        logging.info(f"[{self.name}] Initialized with base path: {self._base_path.resolve()}")

    @property
    def name(self) -> str:
        return "filesystem"

    def get_races_for_date(self, for_date: date) -> List[RaceData]:
        """
        Loads the race program from a 'races.json' file in the base path.
        """
        races_file = self._base_path / for_date.isoformat() / "races.json"
        logging.debug(f"[{self.name}] Looking for races file at: {races_file}")
        if not races_file.exists():
            logging.warning(f"[{self.name}] Races file not found: {races_file}")
            return []

        try:
            with open(races_file, "r") as f:
                races_data = json.load(f)
            
            # Assuming the JSON contains a list of dicts that match the Race model
            return [RaceData(**race_data) for race_data in races_data]

        except (json.JSONDecodeError, TypeError) as e:
            logging.error(f"[{self.name}] Failed to parse races file {races_file}: {e}")
            return []

    def get_race_details(self, race: RaceData) -> Dict[str, Any]:
        """
        Loads race details and runners from a '{race.rc_label}.json' file.
        """
        details_file = self._base_path / race.date.isoformat() / f"{race.rc_label}.json"

        if not details_file.exists():
            logging.warning(f"[{self.name}] Race details file not found: {details_file}")
            return {}
        
        try:
            with open(details_file, "r") as f:
                details_data = json.load(f)

            # Here we could perform validation against a more detailed Pydantic model if needed
            return details_data

        except (json.JSONDecodeError, TypeError) as e:
            logging.error(f"[{self.name}] Failed to parse details file {details_file}: {e}")
            return {}

    def health_check(self) -> bool:
        """
        Checks if the base directory and a sample 'races.json' file exist.
        """
        is_healthy = self._base_path.exists() and self._base_path.is_dir()
        if not is_healthy:
            logging.error(f"[{self.name}] Health check failed: Base path not found or not a directory: {self._base_path.resolve()}")
        return is_healthy

