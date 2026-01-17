# hippique_orchestrator/providers/zoneturf_provider.py
import logging
from datetime import date
from typing import List

from hippique_orchestrator.data_contract import RaceProgram, RaceSnapshotNormalized
from hippique_orchestrator.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)


class ZeturfProvider(BaseProvider):
    """
    Provider for fetching data from Zeturf.

    NOTE: Based on the existing `zoneturf_client.py`, this provider is
    currently only capable of enriching data (fetching stats), not providing
    the initial race program. The core methods are not implemented.
    """

    @property
    def name(self) -> str:
        return "zeturf"

    def get_races_for_date(self, target_date: date) -> List[RaceProgram]:
        """
        Fetches the race program for a specific date from Zeturf.
        
        This functionality is not present in the original `zoneturf_client.py`.
        """
        logger.warning(
            f"'{self.name}' provider does not support fetching race programs."
        )
        raise NotImplementedError(
            f"'{self.name}' provider cannot fetch race programs."
        )

    def get_runners_for_race(self, race_info: RaceProgram) -> RaceSnapshotNormalized:
        """
        Fetches the detailed snapshot of runners for a specific race from Zeturf.

        This functionality is not present in the original `zoneturf_client.py`.
        """
        logger.warning(
            f"'{self.name}' provider does not support fetching runner snapshots."
        )
        raise NotImplementedError(
            f"'{self.name}' provider cannot fetch runner snapshots."
        )

# NOTE: The helper functions from the original `zoneturf_client.py` (`get_chrono_stats`, 
# `resolve_horse_id`, etc.) could be moved here if this provider were to be used for 
# data enrichment in the future. For now, they are omitted as they don't fit the 
# `BaseProvider` interface for program/runner fetching.
