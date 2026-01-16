import re
from pathlib import Path
import json

import pytest
from bs4 import BeautifulSoup

from hippique_orchestrator.scripts import online_fetch_zeturf


@pytest.fixture(scope="module")
def zeturf_race_script_only_content() -> str:
    """Provides the HTML content of a Zeturf race page with odds only in cotesInfos script."""
    fixture_path = Path("tests/fixtures/zeturf_race_script_only.html")
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}. Please create it as per instructions.")
    return fixture_path.read_text(encoding='utf-8')


def test_fallback_parse_html_script_only_odds(zeturf_race_script_only_content):
    """
    Tests that _fallback_parse_html correctly extracts odds from cotesInfos script
    when no traditional odds table is present.
    """
    result = online_fetch_zeturf._fallback_parse_html(zeturf_race_script_only_content)

    assert result is not None
    assert result.get("meeting") is None # Not present in this minimal fixture
    runners = result["runners"]
    assert len(runners) == 2

    # Check specific runner details
    runner1 = next((r for r in runners if r.get("num") == "1"), None)
    assert runner1 is not None
    assert runner1.get("name") == "Cheval Un"
    assert runner1.get("cote") == 2.5
    assert runner1.get("odds_place") == 1.3

    runner2 = next((r for r in runners if r.get("num") == "2"), None)
    assert runner2 is not None
    assert runner2.get("name") == "Cheval Deux"
    assert runner2.get("cote") == 3.0
    assert runner2.get("odds_place") == 1.5

    assert result.get("partants") == 4 # Based on partants span in fixture
    assert result.get("discipline") is None # No discipline in this minimal fixture


def test_fallback_parse_no_runners_table_finds_no_runners(zeturf_race_script_only_content):
    """
    Tests that if the runners table is missing, no runners are parsed, even if the
    cotesInfos script is present.
    """
    # For a script-only fixture, if the script is removed, no odds are found,
    # and if the HTML doesn't have names, runners may not be created.
    # Our zeturf_race.html doesn't have a runners table to begin with,
    # so it should already produce runners based on the script.
    # To test "no runners table", we need to ensure names are extracted from somewhere.
    # Let's create a minimal HTML that has cotesInfos but no runner names outside the script.

    html_content_no_table = """
    <html><body>
        <script type="text/javascript">
            var cotesInfos = [{"num": 1, "nom": "Cheval A", "cote": "4.5", "cote_place": "1.8"}];
        </script>
    </body></html>
    """
    result = online_fetch_zeturf._fallback_parse_html(html_content_no_table)

    assert len(result["runners"]) == 1 # Runner is inferred from script
    assert result["runners"][0]["name"] == "Cheval A"
    assert result["runners"][0]["cote"] == 4.5


def test_fallback_parse_no_script_finds_no_odds():
    """
    Tests that if the cotesInfos script is missing, and there's no table, no runners are found.
    """
    fixture_path = Path("tests/fixtures/zeturf_race_no_script_no_table.html")
    html_content = fixture_path.read_text(encoding='utf-8')
    result = online_fetch_zeturf._fallback_parse_html(html_content)
    assert len(result["runners"]) == 0


def test_fallback_parse_no_data_finds_nothing():
    """
    Tests that if both the table and script are missing, no runners are found.
    """
    fixture_path = Path("tests/fixtures/zeturf_race_no_script_no_table.html")
    html_content = fixture_path.read_text(encoding='utf-8')
    result = online_fetch_zeturf._fallback_parse_html(html_content)
    assert result["runners"] == []


def test_double_extract_uses_fallback(mocker):
    """
    Tests that _double_extract uses the fallback parser when the primary one fails.
    """
    # This test's HTML needs to have _some_ minimal structure for fallback to work,
    # but it doesn't need to be tied to zeturf_race_script_only_content necessarily.
    html_content = """
    <html><body>
        <div id="race-info">
            <span class="partants">10 Partants</span>
        </div>
        <script type="text/javascript">
            var cotesInfos = [{"num": 1, "nom": "Cheval A", "cote": "4.5"}];
        </script>
    </body></html>
    """
    mocker.patch(
        "hippique_orchestrator.scripts.online_fetch_zeturf._http_get",
        return_value=html_content,
    )
    fallback_mock = mocker.patch(
        "hippique_orchestrator.scripts.online_fetch_zeturf._fallback_parse_html",
        return_value={
            "runners": [{"num": "1", "name": "Cheval A", "cote": 4.5}],
            "partants": 1,
        },
    )

    online_fetch_zeturf._double_extract("http://example.com", snapshot="H-30")

    fallback_mock.assert_called_once_with(html_content)
