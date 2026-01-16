import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from hippique_orchestrator.data_contract import (
    RaceData,
    RaceSnapshotNormalized,
    RunnerData,
    RunnerStats,
)
from hippique_orchestrator.scripts.online_fetch_zeturf import fetch_race_snapshot_full
from hippique_orchestrator.sources_interfaces import SourceProvider
from hippique_orchestrator.zoneturf_client import (
    get_chrono_stats,
    get_jockey_trainer_stats,
)

logger = logging.getLogger(__name__)

# Match "R1C1" in either "/R1C1-..." or "-R1C1-..." or "/r1c1/"
_RC_RE = re.compile(r"(?i)(?:^|[\/-])(r\d+c\d+)(?:[\/-]|$)")


def _phase_norm(phase: str) -> str:
    p = (phase or "").upper().replace("-", "").replace("_", "")
    return "H5" if p in ("H5", "H05") else "H30"


class ZeturfSource(SourceProvider):
    """
    SourceProvider implementation for Zeturf.
    This is intended as a fallback source, primarily for snapshots, as it
    does not support fetching a full day's programme.
    """

    @property
    def name(self) -> str:
        return "zeturf"

    async def fetch_programme(self, url: str, **kwargs) -> list[dict[str, Any]]:
        """Zeturf scraper does not support fetching the full daily programme."""
        logger.warning(
            f"[{self.name}] does not support fetching the full programme. Returning empty list."
        )
        return []

    async def fetch_snapshot(self, race_url: str, **kwargs) -> RaceSnapshotNormalized:
        """
        Fetches the detailed snapshot for a single race from Zeturf and
        transforms it into the normalized RaceSnapshotNormalized data contract.
        """
        phase = kwargs.get("phase", "H30")
        date_str = kwargs.get("date")
        log_extra = {
            "correlation_id": kwargs.get("correlation_id"),
            "trace_id": kwargs.get("trace_id"),
            "url": race_url,
        }

        m = _RC_RE.search(race_url)
        if not m:
            raise ValueError(f"[{self.name}] Could not extract R?C? from URL: {race_url}")

        rc_label = m.group(1).upper()  # e.g., "R1C1"
        reunion = rc_label[:2]  # e.g., "R1"
        course = rc_label[2:]  # e.g., "C1"
        ph = _phase_norm(phase)

        logger.info(
            f"[{self.name}] Fetching snapshot for {rc_label} at phase {ph} from {race_url}",
            extra=log_extra,
        )
        
        raw_snapshot = await asyncio.to_thread(
            fetch_race_snapshot_full,
            reunion,  # Pass reunion separately
            course,   # Pass course separately
            ph,
            course_url=race_url,
            date=date_str,
        )

        if not isinstance(raw_snapshot, dict) or not raw_snapshot.get("runners"):
            raise ValueError(
                f"[{self.name}] Failed to get a valid snapshot from Zeturf for {race_url}"
            )

        # Transform the raw dictionary into the Pydantic data contract
        race_date_str = raw_snapshot.get("date")
        if not race_date_str:
            raise ValueError("Date is missing from Zeturf snapshot")
        try:
            race_date = datetime.strptime(race_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid date format in Zeturf snapshot: {race_date_str}") from e

        race_data = RaceData(
            date=race_date,
            rc_label=raw_snapshot.get("rc", rc_label),
            name=raw_snapshot.get("meeting"),
            url=raw_snapshot.get("source_url", race_url),
            discipline=raw_snapshot.get("discipline"),
            distance=raw_snapshot.get("distance"),
            corde=raw_snapshot.get("corde"),
        )

        runners_data = []
        for raw_runner in raw_snapshot.get("runners", []):
            runner_name = raw_runner.get("name", "")
            driver_name = raw_runner.get("jokey") or raw_runner.get("driver")
            trainer_name = raw_runner.get("entraineur")

            # Fetch chrono stats (synchronous, needs to be run in thread)
            horse_stats_raw = await asyncio.to_thread(get_chrono_stats, runner_name)
            
            # Fetch driver stats (synchronous, needs to be run in thread)
            driver_stats_raw = {}
            if driver_name:
                driver_stats_raw = await asyncio.to_thread(get_jockey_trainer_stats, driver_name, "jockey")

            # Fetch trainer stats (synchronous, needs to be run in thread)
            trainer_stats_raw = {}
            if trainer_name:
                trainer_stats_raw = await asyncio.to_thread(get_jockey_trainer_stats, trainer_name, "entraineur")
            
            # Populate RunnerStats
            runner_stats = RunnerStats(source_stats="zoneturf")
            if horse_stats_raw:
                runner_stats.last_3_chrono = horse_stats_raw.get("last_3_chrono", [])
                runner_stats.record_rk = horse_stats_raw.get("record_attele")
            if driver_stats_raw:
                runner_stats.driver_rate = driver_stats_raw.get("win_rate") # Assuming driver rate is win_rate
            if trainer_stats_raw:
                runner_stats.trainer_rate = trainer_stats_raw.get("win_rate") # Assuming trainer rate is win_rate


            runner = RunnerData(
                num=raw_runner["num"],
                nom=runner_name,
                musique=raw_runner.get("musique"),
                odds_win=raw_runner.get("cote"),
                odds_place=raw_runner.get("odds_place"),
                driver=driver_name,
                trainer=trainer_name,
                gains=raw_runner.get("gains"),
                stats=runner_stats, # Assign the populated RunnerStats
            )
            runners_data.append(runner)

        return RaceSnapshotNormalized(
            race=race_data,
            runners=runners_data,
            source_snapshot=self.name,
            meta=raw_snapshot,
        )

    async def fetch_stats_for_runner(self, runner_name: str, **kwargs) -> RunnerStats:
        """Zeturf scraper does not provide detailed runner stats."""
        logger.warning(
            f"[{self.name}] does not provide stats. Returning empty stats object for {runner_name}."
        )
        return RunnerStats(source_stats=self.name)
