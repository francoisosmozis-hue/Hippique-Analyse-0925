
from pathlib import Path
from bs4 import BeautifulSoup
import pytest

from hippique_orchestrator.scrapers import boturfers

@pytest.fixture
def mock_logger(mocker):
    """Mocks the logger for capturing log messages."""
    return mocker.patch("hippique_orchestrator.scrapers.boturfers.logger")

@pytest.fixture
def boturfers_programme_broken_reunion_class_html():
    """Provides the HTML content of a broken Boturfers programme page."""
    fixture_path = Path(__file__).parent / "fixtures" / "boturfers_programme_broken_reunion_class.html"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')

@pytest.fixture
def boturfers_programme_missing_table_html():
    """Provides the HTML content of a Boturfers programme page with a missing table."""
    fixture_path = Path(__file__).parent / "fixtures" / "boturfers_programme_missing_table.html"
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return fixture_path.read_text(encoding='utf-8')

def test_parse_programme_handles_broken_reunion_class(boturfers_programme_broken_reunion_class_html, mock_logger):
    """
    Tests that the scraper can handle a broken reunion class name.
    """
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_programme_broken_reunion_class_html, 'lxml')
    races = fetcher._parse_programme()
    assert races == []
    assert "Aucun onglet de réunion" in mock_logger.warning.call_args[0][0]

def test_parse_programme_handles_missing_race_table(boturfers_programme_missing_table_html, mock_logger):
    """
    Tests that the scraper can handle a missing race table in a reunion.
    """
    fetcher = boturfers.BoturfersFetcher("http://dummy.url")
    fetcher.soup = BeautifulSoup(boturfers_programme_missing_table_html, 'lxml')
    races = fetcher._parse_programme()
    assert "Tableau des courses" in mock_logger.warning.call_args[0][0]
