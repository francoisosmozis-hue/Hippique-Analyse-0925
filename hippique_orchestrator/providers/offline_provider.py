# hippique_orchestrator/providers/offline_provider.py
import json
import logging
from datetime import date
from pathlib import Path
from typing import List

from pydantic import ValidationError

from hippique_orchestrator.data_contract import RaceProgram, RaceSnapshotNormalized
from hippique_orchestrator.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)

# This path should be configured to point to your test fixtures
FIXTURE_DIR = Path("data/ci_sample")


class OfflineProvider(BaseProvider):
    """
    Provider for fetching data from local fixture files.
    Used for testing and CI environments to ensure offline execution.
    """

    @property
    def name(self) -> str:
        return "offline"

    def get_races_for_date(self, target_date: date) -> List[RaceProgram]:
        """
        Loads a race program for a specific date from a local JSON file.
        The file is expected to be named `program_{YYYY-MM-DD}.json`.
        """
        fixture_file = FIXTURE_DIR / f"program_{target_date.strftime('%Y-%m-%d')}.json"
        
        if not fixture_file.exists():
            logger.warning(f"OfflineProvider: Fixture file not found: {fixture_file}")
            return []

        try:
            with open(fixture_file, "r") as f:
                data = json.load(f)
            
            # Assuming the file contains a list of dicts conforming to RaceProgram
            return [RaceProgram(**item) for item in data]
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.error(f"OfflineProvider: Failed to load or validate {fixture_file}: {e}")
            return []

    def get_runners_for_race(self, race_info: RaceProgram) -> RaceSnapshotNormalized | None:
        """
        Loads a detailed race snapshot from a local JSON file.
        The file is expected to be named `snapshot_{reunion}_{race_number}.json`.
        """
        # Generate a file name based on the race info. This needs a consistent naming scheme.
        # Example: R1C1 -> snapshot_R1_1.json
        fixture_file = FIXTURE_DIR / f"snapshot_{race_info.reunion}_{race_info.race_number}.json"

        if not fixture_file.exists():
            logger.warning(f"OfflineProvider: Fixture file not found: {fixture_file}")
            return None

        try:
            with open(fixture_file, "r") as f:
                data = json.load(f)
            return RaceSnapshotNormalized(**data)
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.error(f"OfflineProvider: Failed to load or validate {fixture_file}: {e}")
            return None
