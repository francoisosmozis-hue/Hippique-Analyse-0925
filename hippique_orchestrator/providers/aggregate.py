# hippique_orchestrator/providers/aggregate.py
"""
An aggregate provider that implements fallback logic over a list of sub-providers.
"""
import logging
from datetime import date
from typing import List, Tuple, Dict

from hippique_orchestrator.contracts.models import Race, Runner, OddsSnapshot
from hippique_orchestrator.providers.base import Provider

logger = logging.getLogger(__name__)

class AggregateProvider(Provider):
    """
    A provider that wraps multiple providers and tries them in order until one
    succeeds.
    """
    def __init__(self, providers: List[Provider]):
        if not providers:
            raise ValueError("AggregateProvider requires at least one sub-provider.")
        self.providers = providers
        self._name = "Aggregate"

    @property
    def name(self) -> str:
        return self._name

    def fetch_programme(self, for_date: date) -> List[Race]:
        for provider in self.providers:
            try:
                logger.info(f"Attempting to fetch program for {for_date} with {provider.name}")
                programme = provider.fetch_programme(for_date)
                if programme:
                    logger.info(f"Successfully fetched program with {provider.name}")
                    return programme
            except Exception as e:
                logger.error(f"Provider {provider.name} failed to fetch program: {e}", exc_info=True)
                continue
        logger.warning(f"All providers failed to fetch program for {for_date}.")
        return []

    def fetch_race_details(self, race: Race, phase: str) -> Tuple[List[Runner], OddsSnapshot]:
        for provider in self.providers:
            try:
                logger.info(f"Attempting to fetch details for race {race.race_uid} (phase {phase}) with {provider.name}")
                runners, snapshot = provider.fetch_race_details(race, phase)
                if runners and snapshot:
                    logger.info(f"Successfully fetched details with {provider.name}")
                    # The snapshot from the successful provider already contains the source name
                    return runners, snapshot
            except Exception as e:
                logger.error(f"Provider {provider.name} failed to fetch details for race {race.race_uid}: {e}", exc_info=True)
                continue
        
        logger.warning(f"All providers failed to fetch details for race {race.race_uid} (phase {phase}).")
        # Return empty data structures if all providers fail
        return [], OddsSnapshot(race_uid=race.race_uid, phase=phase, source="N/A")
