import logging
from unittest.mock import AsyncMock, patch

import pytest
from bs4 import BeautifulSoup

from hippique_orchestrator.scrapers.boturfers import (
    BoturfersFetcher,
    fetch_boturfers_programme,
    fetch_boturfers_race_details,
)


@pytest.mark.asyncio
async def test_parse_race_metadata_conditions_from_text_snippet(caplog):
    """
    Test _parse_race_metadata extracts conditions from text snippet if specific tag is missing.
    Covers lines 103-105 of boturfers.py
    """
    html_content = """
        <html>
            <body>
                <div class="info-race">
                    Distance: 2100m - Type: Attelé. Conditions: Prix de la Ville.
                </div>
            </body>
        </html>
    """
    fetcher = BoturfersFetcher(race_url="http://example.com/race")
    fetcher.soup = BeautifulSoup(html_content, "lxml")

    metadata = fetcher._parse_race_metadata()
    assert metadata.get("conditions") == "conditions: prix de la ville."
    assert "Aucune métadonnée de course n'a pu être extraite" not in caplog.text


@pytest.mark.asyncio
async def test_parse_race_metadata_no_metadata_logs_warning(caplog):
    """
    Test _parse_race_metadata logs a warning if no metadata can be extracted.
    Covers lines 109-114 of boturfers.py
    """
    html_content = """
        <html>
            <body>
                <div>No info here</div>
            </body>
        </html>
    """
    fetcher = BoturfersFetcher(race_url="http://example.com/race")
    fetcher.soup = BeautifulSoup(html_content, "lxml")

    with caplog.at_level(logging.WARNING):
        metadata = fetcher._parse_race_metadata()
        assert metadata == {}
        assert (
            "Aucune métadonnée de course n'a pu être extraite de http://example.com/race."
            in caplog.text
        )


@pytest.mark.asyncio
async def test_fetch_boturfers_programme_empty_url_logs_error(caplog):
    """
    Test fetch_boturfers_programme logs an error and returns empty dict for empty URL.
    Covers lines 140-143 of boturfers.py
    """
    with caplog.at_level(logging.ERROR):
        result = await fetch_boturfers_programme(url="")
        assert result == {}
        assert "Aucune URL fournie pour le scraping Boturfers." in caplog.text


@pytest.mark.asyncio
@patch(
    "hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._fetch_html",
    AsyncMock(side_effect=Exception("Mocked fetch error")),
)
async def test_fetch_boturfers_programme_generic_exception(caplog):
    """
    Test fetch_boturfers_programme handles and logs generic exceptions.
    Covers line 151 of boturfers.py
    """
    with caplog.at_level(logging.ERROR):
        result = await fetch_boturfers_programme(url="http://example.com/programme")
        assert result == {}
        assert (
            "Une erreur inattendue est survenue lors du scraping de http://example.com/programme: Mocked fetch error"
            in caplog.text
        )


@pytest.mark.asyncio
async def test_fetch_boturfers_race_details_non_boturfers_url_no_partant(caplog):
    """
    Test fetch_boturfers_race_details does not append /partant for non-Boturfers URLs.
    Covers line 170 of boturfers.py
    """
    # Patch BoturfersFetcher class directly
    with patch("hippique_orchestrator.scrapers.boturfers.BoturfersFetcher") as MockBoturfersFetcher:
        # Configure the mocked fetcher instance
        mock_fetcher_instance = MockBoturfersFetcher.return_value
        mock_fetcher_instance.get_race_snapshot = AsyncMock(
            return_value={
                "source": "boturfers",
                "type": "race_details",
                "url": "http://non-boturfers.com/race/123",  # This should reflect what was actually passed to init
                "scraped_at": "mock_time",
                "race_metadata": {},
                "runners": [{"nom": "Horse"}],
            }
        )

        test_url = "http://non-boturfers.com/race/123"
        result = await fetch_boturfers_race_details(url=test_url)

        # Assert that BoturfersFetcher was called with the untransformed URL
        MockBoturfersFetcher.assert_called_once_with(
            race_url=test_url, correlation_id=None, trace_id=None
        )
        # Also check the result, which should come from the mocked get_race_snapshot
        assert result.get("runners") == [{"nom": "Horse"}]


@pytest.mark.asyncio
@patch(
    "hippique_orchestrator.scrapers.boturfers.BoturfersFetcher._fetch_html",
    AsyncMock(side_effect=Exception("Mocked fetch error")),
)
async def test_fetch_boturfers_race_details_generic_exception(caplog):
    """
    Test fetch_boturfers_race_details handles and logs generic exceptions.
    Covers line 217 of boturfers.py
    """
    with caplog.at_level(logging.ERROR):
        result = await fetch_boturfers_race_details(url="http://example.com/race/details")
        assert result == {}
        assert (
            "Une erreur inattendue est survenue lors du scraping des détails de http://example.com/race/details: Mocked fetch error"
            in caplog.text
        )
