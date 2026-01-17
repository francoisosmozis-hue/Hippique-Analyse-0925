# hippique_orchestrator/sources/geny_provider.py
from __future__ import annotations

import logging
from datetime import date
from typing import List

from hippique_orchestrator.data_contract import RaceProgram, RaceSnapshotNormalized
from hippique_orchestrator.providers.base_provider import BaseProvider

logger = logging.getLogger(__name__)


class GenyProvider(BaseProvider):
    """
    Provider for Geny.com data.
    NOTE: This is a stub and does not contain a real implementation for program/runner fetching.
    """

    @property
    def name(self) -> str:
        return "geny"

    def get_races_for_date(self, target_date: date) -> List[RaceProgram]:
        """This provider does not implement program fetching."""
        logger.warning(f"'{self.name}' provider does not support fetching race programs.")
        raise NotImplementedError(f"'{self.name}' provider cannot fetch race programs.")

    def get_runners_for_race(self, race_info: RaceProgram) -> RaceSnapshotNormalized | None:
        """This provider does not implement runner fetching."""
        logger.warning(f"'{self.name}' provider does not support fetching runner snapshots.")
        raise NotImplementedError(f"'{self.name}' provider cannot fetch runner snapshots.")

