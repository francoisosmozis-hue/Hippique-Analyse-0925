from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from hippique_orchestrator.scrapers import boturfers


@pytest.fixture
def mock_logger(mocker):
    """Mocks the logger for capturing log messages."""
    return mocker.patch("hippique_orchestrator.scrapers.boturfers.logger")


@pytest.fixture
def boturfers_programme_sample_html():
    """Provides the HTML content of a sample Boturfers programme page."""
    fixture_path = Path(__file__).parent / "fixtures" / "boturfers_programme_sample.html"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')


@pytest.fixture
def boturfers_racedetail_sample_html():
    """Provides the HTML content of a sample Boturfers race detail page."""
    fixture_path = Path(__file__).parent / "fixtures" / "boturfers_racedetail_sample.html"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')


@pytest.fixture
def boturfers_programme_broken_reunion_class_html():
    """Provides the HTML content of a broken Boturfers programme page."""
    fixture_path = (
        Path(__file__).parent / "fixtures" / "boturfers_programme_broken_reunion_class.html"
    )
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')


@pytest.fixture
def boturfers_programme_missing_table_html():
    """Provides the HTML content of a Boturfers programme page with a missing table."""
    fixture_path = Path(__file__).parent / "fixtures" / "boturfers_programme_missing_table.html"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')


def test_parse_programme_handles_broken_reunion_class(
    boturfers_programme_broken_reunion_class_html, mock_logger
):
    """
    Tests that the scraper can handle a broken reunion class name.
    """
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_programme_broken_reunion_class_html, 'lxml')
    races = fetcher._parse_programme()
    assert races == []
    assert "Aucun onglet de réunion" in mock_logger.warning.call_args[0][0]


def test_parse_programme_handles_missing_race_table(
    boturfers_programme_missing_table_html, mock_logger
):
    """
    Tests that the scraper can handle a missing race table in a reunion.
    """
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_programme_missing_table_html, 'lxml')
    _ = fetcher._parse_programme()
    assert "Tableau des courses" in mock_logger.warning.call_args[0][0]


def test_parse_programme_from_static_fixture(boturfers_programme_sample_html):
    """
    Tests that the scraper can correctly parse a programme from a static HTML fixture.
    This acts as a contract for the expected HTML structure.
    """
    fetcher = boturfers.BoturfersFetcher("http://base.url")
    fetcher.soup = BeautifulSoup(boturfers_programme_sample_html, 'lxml')
    races = fetcher._parse_programme()

    assert len(races) == 3

    # Test R1C1
    assert races[0]["rc"] == "R1C1"
    assert races[0]["name"] == "PRIX DE LA FIXTURE"
    assert races[0]["reunion"] == "R1"
    assert races[0]["start_time"] == "13:50"
    assert races[0]["runners_count"] == 16
    assert races[0]["url"] == "http://base.url/courses/2025-01-01/fictif/r1c1-prix-de-la-fixture"

    # Test R1C2
    assert races[1]["rc"] == "R1C2"
    assert races[1]["name"] == "PRIX DU TEST UNITAIRE"
    assert races[1]["reunion"] == "R1"
    assert races[1]["start_time"] == "14:25"
    assert races[1]["runners_count"] == 12

    # Test R2C1
    assert races[2]["rc"] == "R2C1"
    assert races[2]["reunion"] == "R2"
    assert races[2]["start_time"] == "16:00"
    assert races[2]["runners_count"] == 10


def test_parse_race_details_from_static_fixture(boturfers_racedetail_sample_html, mock_logger):
    """
    Tests that the scraper can correctly parse race details from a static HTML fixture,
    ensuring robustness against malformed data.
    """
    fetcher = boturfers.BoturfersFetcher("http://race.url/partant")
    fetcher.soup = BeautifulSoup(boturfers_racedetail_sample_html, 'lxml')
    runners = fetcher._parse_race_runners_from_details_page()

    # Should parse 2 valid runners and skip the malformed ones
    assert len(runners) == 3
    mock_logger.warning.assert_any_call(
        "Failed to parse a runner row: 'NoneType' object has no attribute 'text'. Row skipped.",
        extra={'correlation_id': None, 'trace_id': None},
    )

    # Test Runner 1
    assert runners[0]["num"] == 1
    assert runners[0]["nom"] == "AS DU TEST"
    assert runners[0]["jockey"] == "J. Testeur"
    assert runners[0]["entraineur"] == "E. Scripter"
    assert runners[0]["odds_win"] == 4.5
    assert runners[0]["odds_place"] == 1.8
    assert runners[0]["musique"] == "1p 2p (23) 3p"
    assert runners[0]["gains"] == "150000€"

    # Test Runner 2
    assert runners[1]["num"] == 2
    assert runners[1]["nom"] == "ROI DE LA QA"
    assert runners[1]["jockey"] == "M. Coverage"
    assert runners[1]["entraineur"] == "P. Integration"
    assert runners[1]["odds_win"] == 8.0
    assert runners[1]["odds_place"] == 2.5
    assert runners[1]["musique"] == "4h 5p 1p"
    assert runners[1]["gains"] == "95000€"

    # Test Runner 3 (MISS MOCK) with corrected jockey/trainer parsing
    assert runners[2]["num"] == 3
    assert runners[2]["nom"] == "MISS MOCK"
    assert runners[2]["jockey"] == "N/A"  # Jockey is missing in the fixture, so it should be N/A
    assert runners[2]["entraineur"] == "F. Fixture"
    assert runners[2]["odds_win"] == 12.0
    assert runners[2]["odds_place"] is None  # Cote placée manquante
    assert runners[2]["musique"] == "Da"
    assert runners[2]["gains"] == "30000€"

    metadata = fetcher._parse_race_metadata()
    assert metadata["distance"] == 2400
    assert metadata["type_course"] == "Plat"
    assert metadata["corde"] == "Gauche"
    assert "pour chevaux entiers" in metadata["conditions"]


def test_programme_fixture_has_expected_structure(boturfers_programme_sample_html):
    """
    Acts as a contract test to ensure the scraper's critical HTML selectors are present.
    If this fails, the live site has likely changed its structure.
    """
    soup = BeautifulSoup(boturfers_programme_sample_html, 'lxml')

    # Assert critical containers exist
    assert soup.select_one("div.tab-content") is not None, "Missing main tab content container."
    assert soup.select("div.tab-pane[id^=r]"), "Missing reunion tab panes."

    # Assert table structure exists in the first reunion
    first_reunion = soup.select_one("div.tab-pane[id^=r]")
    assert first_reunion is not None
    assert first_reunion.select_one("table.table.data.prgm") is not None, "Missing programme table."
    assert first_reunion.select("tbody tr"), "Missing race rows in table."

    # Assert key data cells exist in the first row
    first_race_row = first_reunion.select_one("tbody tr")
    assert first_race_row is not None
    assert first_race_row.select_one("td.crs") is not None, "Missing race name cell (td.crs)."
    assert first_race_row.select_one("td.hour") is not None, "Missing start time cell."
