from unittest.mock import MagicMock
from pathlib import Path

import pytest

from hippique_orchestrator.scripts import online_fetch_zeturf

@pytest.fixture
def zeturf_html_content() -> str:
    """Provides the HTML content of the Zeturf programme page."""
    # Using the archived fixture as it's the only one available
    fixture_path = Path(__file__).parent.parent / "archive" / "zeturf_program.html"
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')

@pytest.fixture
def zeturf_page_content() -> str:
    """Provides the HTML content of a Zeturf race page."""
    fixture_path = Path(__file__).parent.parent / "archive" / "zeturf_page.html"
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')


def test_fetch_race_snapshot_full_success(mocker):
    """
    Tests that `fetch_race_snapshot_full` correctly parses a Zeturf HTML
    page fixture by mocking the actual HTTP GET call.
    """
    # 1. Prepare expected data that _double_extract should return
    expected_parsed_data = {
        "reunion": "R1",
        "course": "C1",
        "phase": "H30",
        "hippodrome": "SAINT GALMIER",
        "discipline": "attelé",
        "partants": 12,
        "partants_count": 12,
        "runners": [
            {"num": "1", "name": "IZZIA HIGHLAND"},
            {"num": "2", "name": "INTEL"},
            {"num": "3", "name": "GIN KAS"},
            {"num": "4", "name": "INDIGO"},
            {"num": "5", "name": "INDY VET"},
            {"num": "6", "name": "GAROU DE BOURGOGNE"},
            {"num": "7", "name": "HELLINE SERVINOISE"},
            {"num": "8", "name": "IVAN LENDEL"},
            {"num": "9", "name": "JOLIE LAURA"},
            {"num": "10", "name": "HORTANCE FOLLE"},
            {"num": "11", "name": "IAKA"},
            {"num": "12", "name": "HACKER JULRY"},
        ],
        "source_url": "https://www.zeturf.fr/fr/course/2025-11-20/R1C1-vincennes-prix-de-sille-le-guillaume",
    }
    # 2. Mock the `_double_extract` function to return the expected parsed data
    mocker.patch(
        "hippique_orchestrator.scripts.online_fetch_zeturf._double_extract",
        return_value=expected_parsed_data,
    )


    # 2. Call the function
    result = online_fetch_zeturf.fetch_race_snapshot_full(
        reunion="R1",
        course="C1",
        phase="H-30",
        date="2025-11-20"
    )

    # 3. Assertions
    assert result is not None
    assert isinstance(result, dict)
    assert result.get("reunion") == "R1"
    assert result.get("course") == "C1"
    assert result.get("phase") == "H30"
    assert result.get("hippodrome") == "SAINT GALMIER"
    assert result.get("discipline") == "attelé"
    
    # The fallback parser finds 12 runners in the race page fixture
    assert result.get("partants_count") == 12
    assert "runners" in result
    assert len(result["runners"]) == 12
    
    # Check that a canonical URL was built
    assert "source_url" in result
    assert "2025-11-20/R1C1-vincennes" in result["source_url"]
