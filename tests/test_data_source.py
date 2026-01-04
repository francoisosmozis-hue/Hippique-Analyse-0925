"""
Tests for the data_source abstraction layer.
"""
from unittest.mock import AsyncMock, patch

import pytest

from hippique_orchestrator import data_source


@pytest.mark.asyncio
async def test_fetch_programme_routes_to_boturfers():
    """
    Ensures fetch_programme correctly routes to the boturfers scraper.
    """
    with patch("hippique_orchestrator.data_source.boturfers.fetch_boturfers_programme", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"status": "ok"}
        url = "http://example.com"
        
        result = await data_source.fetch_programme(url, correlation_id="test-id")

        assert result == {"status": "ok"}
        mock_fetch.assert_called_once_with(url, correlation_id="test-id", trace_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "race_url, expected_scraper_path",
    [
        (
            "https://www.boturfers.fr/c/2025-01-01/r1c1",
            "hippique_orchestrator.data_source.boturfers.fetch_boturfers_race_details",
        ),
        (
            "http://some-other-site.com/race",
            "hippique_orchestrator.data_source.boturfers.fetch_boturfers_race_details",
        ),
    ],
)
async def test_fetch_race_details_routes_to_boturfers(race_url, expected_scraper_path):
    """
    Ensures fetch_race_details routes non-Zeturf URLs to the boturfers scraper.
    """
    with patch(expected_scraper_path, new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"source": "boturfers"}
        
        result = await data_source.fetch_race_details(race_url, correlation_id="test-id")

        assert result == {"source": "boturfers"}
        mock_fetch.assert_called_once_with(race_url, correlation_id="test-id", trace_id=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "race_url, expected_scraper_path",
    [
        (
            "https://www.zeturf.fr/fr/course/2025-12-25/R1C2-test",
            "hippique_orchestrator.data_source.fetch_zeturf_race_details",
        ),
        (
            "http://zeturf.com/R1C1",
            "hippique_orchestrator.data_source.fetch_zeturf_race_details",
        ),
    ],
)
async def test_fetch_race_details_routes_to_zeturf(race_url, expected_scraper_path):
    """
    Ensures fetch_race_details routes ZEturf URLs to the zeturf scraper.
    """
    with patch(expected_scraper_path, new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"source": "zeturf"}
        
        result = await data_source.fetch_race_details(race_url, phase="H5", date="2025-12-25")

        assert result == {"source": "zeturf"}
        mock_fetch.assert_called_once_with(race_url, phase="H5", date="2025-12-25")
