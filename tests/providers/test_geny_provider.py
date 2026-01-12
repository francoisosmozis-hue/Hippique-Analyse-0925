from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from hippique_orchestrator.data_contract import RunnerStats
from hippique_orchestrator.sources.geny_provider import GenyProvider


@pytest.fixture
def geny_provider():
    # No need to mock httpx for these tests as we patch _fetch_page
    return GenyProvider()


# Sample HTML for a jockey page on Geny
SAMPLE_GENY_JOCKEY_HTML = """
<html>
<body>
    <table class="table-statistiques-detaillees">
        <tbody>
            <tr>
                <td>Courses disputées</td>
                <td>1234</td>
            </tr>
            <tr>
                <td>% Vict.</td>
                <td>15,5 %</td>
            </tr>
        </tbody>
    </table>
</body>
</html>
"""


def test_geny_provider_initialization(geny_provider):
    assert geny_provider is not None
    assert geny_provider._rate_limiter.locked() is False


@pytest.mark.asyncio
async def test_fetch_stats_for_runner_returns_stats(geny_provider):
    runner_data = {"driver": "Y. LEBOURGEOIS", "trainer": "T. DUVALDESTIN"}

    with patch.object(
        geny_provider, "_fetch_page", AsyncMock(return_value=SAMPLE_GENY_JOCKEY_HTML)
    ) as mock_fetch:
        stats = await geny_provider.fetch_stats_for_runner(
            "Some Horse", "Trot Attelé", runner_data
        )

        mock_fetch.assert_called_once_with("/jockey/y-lebourgeois")
        assert isinstance(stats, RunnerStats)
        assert stats.source_stats == "Geny"
        assert stats.driver_rate == 0.155
        assert stats.trainer_rate is None


@pytest.mark.asyncio
async def test_fetch_stats_for_runner_handles_no_driver(geny_provider):
    runner_data = {"trainer": "T. DUVALDESTIN"} # No driver
    with patch.object(
        geny_provider, "_fetch_page", AsyncMock(return_value=None)
    ) as mock_fetch:
        stats = await geny_provider.fetch_stats_for_runner(
            "Some Horse", "Trot Attelé", runner_data
        )
        # Should not attempt to fetch if there is no entity name
        mock_fetch.assert_not_called()
        assert isinstance(stats, RunnerStats)
        assert stats.driver_rate is None
        assert stats.source_stats is None


@pytest.mark.asyncio
async def test_fetch_stats_for_runner_handles_fetch_failure(geny_provider):
    runner_data = {"driver": "Y. LEBOURGEOIS", "trainer": "T. DUVALDESTIN"}
    with patch.object(
        geny_provider, "_fetch_page", AsyncMock(return_value=None)
    ) as mock_fetch:
        stats = await geny_provider.fetch_stats_for_runner(
            "Some Horse", "Trot Attelé", runner_data
        )
        mock_fetch.assert_called_once()
        assert isinstance(stats, RunnerStats)
        assert stats.driver_rate is None


@pytest.mark.asyncio
async def test_fetch_stats_uses_cache(geny_provider):
    runner_data = {"driver": "Y. LEBOURGEOIS", "trainer": "T. DUVALDESTIN"}
    
    with patch.object(
        geny_provider, "_fetch_page", AsyncMock(return_value=SAMPLE_GENY_JOCKEY_HTML)
    ) as mock_fetch:
        # First call, should fetch
        stats1 = await geny_provider.fetch_stats_for_runner("Horse A", "Trot", runner_data)
        mock_fetch.assert_called_once()
        assert stats1.driver_rate == 0.155

        # Second call, should use cache
        stats2 = await geny_provider.fetch_stats_for_runner("Horse B", "Trot", runner_data)
        # The mock should still have been called only once
        mock_fetch.assert_called_once()
        assert stats2.driver_rate == 0.155
