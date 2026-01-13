from __future__ import annotations

from datetime import date
from datetime import time as dt_time
from unittest.mock import patch

import pytest

from hippique_orchestrator.data_contract import RaceSnapshotNormalized, RunnerStats
from hippique_orchestrator.sources.zeturf_provider import ZeturfProvider


@pytest.fixture
def zeturf_provider():
    """
    Provides a ZeturfProvider with a mocked _http_get_sync method
    that returns content from a static offline fixture file.
    This ensures tests are deterministic and do not perform network calls.
    """
    with open("tests/fixtures/zeturf/2024-01-11_R1C1.html") as f:
        html_content = f.read()

    with patch("hippique_orchestrator.sources.zeturf_provider.ZeturfProvider._http_get_sync", return_value=html_content) as mock_http_get:
        provider = ZeturfProvider()
        provider._http_get_sync_mock = mock_http_get  # Attach mock for inspection if needed
        yield provider


def test_zeturf_provider_initialization(zeturf_provider):
    assert zeturf_provider is not None


@pytest.mark.asyncio
async def test_fetch_snapshot_returns_normalized_data(zeturf_provider):
    race_url = "https://www.zeturf.fr/fr/course/2024-01-11/R1C1-prix-de-la-course"
    snapshot = await zeturf_provider.fetch_snapshot(race_url)

    assert isinstance(snapshot, RaceSnapshotNormalized)
    assert snapshot.source_snapshot == "Zeturf"

    # Test RaceData
    assert snapshot.race.date == date(2024, 1, 11)
    assert snapshot.race.rc_label == "R1C1"
    assert snapshot.race.discipline == "Trot Attelé"
    assert snapshot.race.start_time_local == dt_time(14, 30)

    # Test RunnerData
    assert len(snapshot.runners) == 2

    runner1 = snapshot.runners[0]
    assert runner1.num == 1
    assert runner1.nom == "Gagnant"
    assert runner1.odds_win == pytest.approx(2.5)
    assert runner1.odds_place == pytest.approx(1.35)

    runner2 = snapshot.runners[1]
    assert runner2.num == 2
    assert runner2.nom == "Placé"
    assert runner2.odds_win == pytest.approx(5.0)
    assert runner2.odds_place == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_fetch_snapshot_handles_http_error(zeturf_provider):
    zeturf_provider._http_get_sync_mock.side_effect = RuntimeError("HTTP 404")

    race_url = "https://www.zeturf.fr/fr/course/2024-01-11/R1C1-prix-de-la-course"
    snapshot = await zeturf_provider.fetch_snapshot(race_url)

    assert snapshot.source_snapshot == "Zeturf_Failed"
    assert len(snapshot.runners) == 0


@pytest.mark.asyncio
async def test_fetch_snapshot_handles_empty_runners(zeturf_provider):
    zeturf_provider._http_get_sync_mock.return_value = "<html><body></body></html>"

    race_url = "https://www.zeturf.fr/fr/course/2024-01-11/R1C1-prix-de-la-course"
    snapshot = await zeturf_provider.fetch_snapshot(race_url)

    assert snapshot.source_snapshot == "Zeturf_Failed"
    assert len(snapshot.runners) == 0


@pytest.mark.asyncio
async def test_fetch_stats_for_runner_returns_empty_stats(zeturf_provider):
    stats = await zeturf_provider.fetch_stats_for_runner("any_runner")
    assert isinstance(stats, RunnerStats)
    assert stats.driver_rate is None
    assert stats.trainer_rate is None
