# hippique_orchestrator/providers/boturfers_provider.py
from datetime import date
from typing import List, Tuple

from hippique_orchestrator.contracts.models import Race, Runner, OddsSnapshot
from hippique_orchestrator.providers.base import Provider

class BoturfersProvider(Provider):
    """Live implementation for Boturfers. Not implemented in this scope."""

    def __init__(self, base_url: str, timeout_seconds: int = 30):
        super().__init__()
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "Boturfers-Live"

    def fetch_programme(self, for_date: date) -> List[Race]:
        raise NotImplementedError("Live Boturfers provider is not implemented.")

    def fetch_race_details(self, race: Race, phase: str) -> Tuple[List[Runner], OddsSnapshot]:
        raise NotImplementedError("Live Boturfers provider is not implemented.")
