import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from hippique_orchestrator.scripts import online_fetch_zeturf


@pytest.fixture
def zeturf_page_content() -> str:
    """Provides the HTML content of a Zeturf race page from an archived fixture."""
    fixture_path = Path(__file__).parent.parent.parent / "archive" / "zeturf_page.html"
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')


def test_double_extract_parses_real_html_fixture(zeturf_page_content, mocker):
    """
    Validates the REAL HTML parsing logic of the Zeturf scraper using a fixture.
    """
    mock_response = mocker.MagicMock()
    mock_response.status_code = 200
    mock_response.text = zeturf_page_content
    mocker.patch("requests.get", return_value=mock_response)

    result = online_fetch_zeturf.fetch_race_snapshot_full(
        reunion="R1", course="C1", phase="H-30", date="2025-11-20"
    )

    assert result is not None
    assert result.get("hippodrome") == "SAINT GALMIER"
    runners = result["runners"]
    assert len(runners) == 12
    # Check that data from both table (name) and script (cote) are present
    assert runners[0]["name"] == "IZZIA HIGHLAND"
    assert runners[0]["cote"] == 6.5


def test_fallback_parse_no_runners_table_finds_no_runners(zeturf_page_content):
    """
    Tests that if the runners table is missing, no runners are parsed, even if the
    cotesInfos script is present.
    """
    soup = BeautifulSoup(zeturf_page_content, "lxml")
    if table := soup.find("table", class_="table-runners"):
        table.extract()

    result = online_fetch_zeturf._fallback_parse_html(str(soup))

    assert result["runners"] == []


def test_fallback_parse_no_script_finds_no_odds(zeturf_page_content):
    """
    Tests that if the cotesInfos script is missing, runners are parsed but have no odds.
    """
    soup = BeautifulSoup(zeturf_page_content, "lxml")
    if script := soup.find("script", string=re.compile("cotesInfos")):
        script.extract()

    result = online_fetch_zeturf._fallback_parse_html(str(soup))

    assert len(result["runners"]) == 12
    assert result["runners"][0]["name"] == "IZZIA HIGHLAND"
    # Assert that the 'cote' key is missing, as it comes only from the script
    assert "cote" not in result["runners"][0]


def test_fallback_parse_no_data_finds_nothing(zeturf_page_content):
    """
    Tests that if both the table and script are missing, no runners are found.
    """
    soup = BeautifulSoup(zeturf_page_content, "lxml")
    if table := soup.find("table", class_="table-runners"):
        table.extract()
    if script := soup.find("script", string=re.compile("cotesInfos")):
        script.extract()

    result = online_fetch_zeturf._fallback_parse_html(str(soup))

    assert len(result["runners"]) == 0


def test_double_extract_uses_fallback(mocker):
    """
    Tests that _double_extract uses the fallback parser when the primary one fails.
    """
    html_content = "<html><body>Some content</body></html>"
    mocker.patch(
        "hippique_orchestrator.scripts.online_fetch_zeturf._http_get",
        return_value=html_content,
    )
    fallback_mock = mocker.patch(
        "hippique_orchestrator.scripts.online_fetch_zeturf._fallback_parse_html",
        return_value={"runners": []},
    )

    online_fetch_zeturf._double_extract("http://example.com", snapshot="H-30")

    fallback_mock.assert_called_once_with(html_content)
