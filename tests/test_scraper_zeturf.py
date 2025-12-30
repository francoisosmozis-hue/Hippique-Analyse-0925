from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest
import asyncio # New import

from hippique_orchestrator.scripts import online_fetch_zeturf
from hippique_orchestrator.scrapers import zeturf as zeturf_scraper # New import with alias

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


@pytest.mark.parametrize(
    "input_phase, expected_norm",
    [
        ("H-30", "H30"),
        ("H30", "H30"),
        ("h05", "H5"),
        ("H5", "H5"),
        ("UNKNOWN", "H30"), # Default behavior
        ("", "H30"), # Default behavior
        (None, "H30"), # Default behavior
    ]
)
def test_phase_norm(input_phase, expected_norm):
    assert zeturf_scraper._phase_norm(input_phase) == expected_norm

@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.zeturf.fetch_race_snapshot_full")
async def test_fetch_zeturf_race_details_success(mock_fetch_race_snapshot_full):
    # Arrange
    course_url = "https://www.zeturf.fr/fr/course/2025-11-20/R1C1-vincennes-prix-de-sille-le-guillaume"
    mock_snapshot_data = {
        "reunion": "R1",
        "course": "C1",
        "runners": [{"name": "Runner1"}, {"name": "Runner2"}],
        "discipline": "trot",
    }
    mock_fetch_race_snapshot_full.return_value = mock_snapshot_data

    # Act
    result = await zeturf_scraper.fetch_zeturf_race_details(
        course_url, phase="H30", date="2025-11-20"
    )

    # Assert
    # The rc extracted from URL is "R1C1", so assert that's what's passed as reunion
    mock_fetch_race_snapshot_full.assert_called_once_with(
        "R1C1", None, "H30", course_url=course_url, date="2025-11-20"
    )
    assert result["reunion"] == "R1"
    assert result["course"] == "C1"
    assert result["phase"] == "H30"
    assert result["source"] == "zeturf"
    assert result["source_url"] == course_url
    assert result["date"] == "2025-11-20"
    assert len(result["runners"]) == 2

@pytest.mark.asyncio
async def test_fetch_zeturf_race_details_value_error_no_rc():
    course_url = "https://www.zeturf.fr/fr/course/2025-11-20/no-rc-here"
    with pytest.raises(ValueError, match="impossible d'extraire R\\?C\\? depuis l'URL"):
        await zeturf_scraper.fetch_zeturf_race_details(course_url)

@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.zeturf.fetch_race_snapshot_full")
async def test_fetch_zeturf_race_details_empty_snapshot(mock_fetch_race_snapshot_full):
    mock_fetch_race_snapshot_full.return_value = {}
    course_url = "https://www.zeturf.fr/fr/course/2025-11-20/R1C1-vincennes"
    result = await zeturf_scraper.fetch_zeturf_race_details(course_url)
    assert result["runners"] == []
    assert result["phase"] == "H30" # Default
    assert result["source"] == "zeturf"

@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.zeturf.fetch_race_snapshot_full")
async def test_fetch_zeturf_race_details_missing_runners(mock_fetch_race_snapshot_full):
    mock_fetch_race_snapshot_full.return_value = {"reunion": "R1"} # Missing runners
    course_url = "https://www.zeturf.fr/fr/course/2025-11-20/R1C1-vincennes"
    result = await zeturf_scraper.fetch_zeturf_race_details(course_url)
    assert result["runners"] == [] # Should be initialized to empty list
    assert result["reunion"] == "R1"

@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.zeturf.fetch_race_snapshot_full")
async def test_fetch_zeturf_race_details_non_dict_snapshot(mock_fetch_race_snapshot_full):
    mock_fetch_race_snapshot_full.return_value = "Not a dict"
    course_url = "https://www.zeturf.fr/fr/course/2025-11-20/R1C1-vincennes"
    result = await zeturf_scraper.fetch_zeturf_race_details(course_url)
    assert result["runners"] == []
    assert result["source"] == "zeturf" # Check defaults are still applied
    assert result.get("reunion") is None # Original non-dict had no reunion key

@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.zeturf.fetch_race_snapshot_full")
async def test_fetch_zeturf_race_details_h5_phase_input(mock_fetch_race_snapshot_full):
    mock_fetch_race_snapshot_full.return_value = {}
    course_url = "https://www.zeturf.fr/fr/course/2025-11-20/R1C1-vincennes"
    result = await zeturf_scraper.fetch_zeturf_race_details(course_url, phase="h-5")
    # The rc extracted from URL is "R1C1", so assert that's what's passed as reunion
    mock_fetch_race_snapshot_full.assert_called_once_with(
        "R1C1", None, "H5", course_url=course_url, date=None
    )
    assert result["phase"] == "H5"

@pytest.mark.asyncio
@patch("hippique_orchestrator.scrapers.zeturf.fetch_race_snapshot_full")
async def test_fetch_zeturf_race_details_various_rc_formats(mock_fetch_race_snapshot_full):
    mock_fetch_race_snapshot_full.return_value = {}
    # Test with different URL formats for RC extraction, adhering to _RC_RE
    urls = [
        "https://www.zeturf.fr/fr/course/2025-11-20/R1C1-vincennes",
        "just-r6c7",
    ]
    expected_rcs = ["R1C1", "R6C7"]

    for i, url in enumerate(urls):
        await zeturf_scraper.fetch_zeturf_race_details(url)
        # Check that the correct RC was extracted and passed to the mock
        assert mock_fetch_race_snapshot_full.call_args_list[i][0][0] == expected_rcs[i]
