# tests/providers/file_based_provider.py
import logging
import os
from datetime import date, datetime
from typing import List, Tuple
from bs4 import BeautifulSoup

from hippique_orchestrator.contracts.models import Race, Runner, OddsSnapshot
from hippique_orchestrator.contracts.ids import make_race_uid, make_runner_uid, normalize_name
from hippique_orchestrator.providers.base import Provider

logger = logging.getLogger(__name__)

class FileBasedProvider(Provider):
    """A test provider that reads data from local HTML fixture files."""
    def __init__(self, fixtures_path: str = "tests/fixtures"):
        self.fixtures_path = fixtures_path
        self._name = "File-Boturfers"

    @property
    def name(self) -> str:
        return self._name

    def fetch_programme(self, for_date: date) -> List[Race]:
        # Hardcoded program matching our fixtures.
        race_time = datetime.combine(for_date, datetime.min.time()).replace(hour=13, minute=50)
        race = Race(
            race_uid=make_race_uid(
                race_date=for_date.isoformat(),
                venue="VINCENNES",
                race_number=1,
                discipline="ATTELE",
                distance_m=2700,
                scheduled_time_local=race_time.isoformat()
            ),
            meeting_ref="MOCK_M1",
            race_number=1,
            scheduled_time_local=race_time,
            discipline="ATTELE",
            distance_m=2700,
            runners_count=2,
        )
        return [race]

    def fetch_race_details(self, race: Race, phase: str) -> Tuple[List[Runner], OddsSnapshot]:
        html_path = os.path.join(
            self.fixtures_path, "html", "boturfers", race.scheduled_time_local.date().isoformat(),
            f"R{race.meeting_ref[-1]}C{race.race_number}__{phase}.html"
        )
        
        if not os.path.exists(html_path):
            raise FileNotFoundError(f"Fixture not found: {html_path}")

        with open(html_path, 'r') as f:
            html_content = f.read()

        runners, odds_place = self._parse_html(race, html_content)
        
        snapshot = OddsSnapshot(
            race_uid=race.race_uid,
            phase=phase,
            odds_place=odds_place,
            source=self.name
        )
        return runners, snapshot

    def _parse_html(self, race: Race, html_content: str) -> Tuple[List[Runner], dict]:
        soup = BeautifulSoup(html_content, 'html.parser')
        runners = []
        odds_place = {}
        
        runner_divs = soup.select("#odds-table .runner")
        for r_div in runner_divs:
            parts = [s.strip() for s in r_div.find_all(string=True) if s.strip()]
            if len(parts) < 2:
                continue

            prog_num = int(parts[0])
            horse_name_norm = normalize_name(parts[1])
            runner_uid = make_runner_uid(race.race_uid, prog_num, horse_name_norm)

            runners.append(Runner(
                runner_uid=runner_uid,
                race_uid=race.race_uid,
                program_number=prog_num,
                name_norm=horse_name_norm,
                driver_jockey=normalize_name(parts[2]) if len(parts) > 2 else None,
                trainer=normalize_name(parts[3]) if len(parts) > 3 else None,
            ))

            try:
                odds_place[runner_uid] = float(parts[-1])
            except (ValueError, IndexError):
                logger.warning(f"Could not parse odds for runner {prog_num}")
                continue
        return runners, odds_place