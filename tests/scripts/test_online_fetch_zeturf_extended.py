import pytest
from pathlib import Path
import re

from hippique_orchestrator.scripts import online_fetch_zeturf

@pytest.fixture
def zeturf_course_html():
    """Returns the content of the Zeturf course page fixture."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "zeturf_course_page.html"
    return fixture_path.read_text(encoding="utf-8")

@pytest.fixture
def malformed_zeturf_html(zeturf_course_html):
    """A malformed version of the Zeturf HTML with the runners table removed."""
    return re.sub(
        r'<table[^>]+class="[^"]*table-runners[^"]*"[^>]*>.*?</table>',
        "",
        zeturf_course_html,
        flags=re.DOTALL,
    )

def test_fallback_parse_html_no_runners_table(malformed_zeturf_html):
    """
    Tests that _fallback_parse_html handles cases where the runners table is missing.
    """
    parsed_data = online_fetch_zeturf._fallback_parse_html(malformed_zeturf_html)

    assert parsed_data is not None
    assert isinstance(parsed_data, dict)

    # It should still extract other metadata
    assert parsed_data["meeting"] == "SAINT GALMIER"
    assert parsed_data["discipline"] == "attelé"
    assert parsed_data["partants"] == 12

    # The runners list should be empty
    assert "runners" in parsed_data
    assert isinstance(parsed_data["runners"], list)
    assert len(parsed_data["runners"]) == 0

def test_fallback_parse_html_runner_missing_data(zeturf_course_html):
    """
    Tests that _fallback_parse_html can handle a runner row with missing odds data.
    """
    # Remove the odds from the first runner, both from the table and the script
    modified_html = zeturf_course_html.replace(
        '<span class="cote">6.5</span>', "", 1
    )
    # Also remove the script fallback
    modified_html = re.sub(
        r"cotesInfos: \{.*\}",
        "cotesInfos: {}",
        modified_html
    )

    parsed_data = online_fetch_zeturf._fallback_parse_html(modified_html)

    assert parsed_data is not None
    runners = parsed_data["runners"]
    assert len(runners) == 12

    runner_1 = next((r for r in runners if r.get("num") == "1"), None)
    assert runner_1 is not None
    assert runner_1["name"] == "IZZIA HIGHLAND"
    assert "cote" not in runner_1  # The odds should be missing
    # This key is not present in the new parsing logic
    # assert runner_1["odds_place"] == 2.25


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Simple case
        ({"num": "1", "name": "HORSE A", "cote": "12,5"}, {"num": "1", "name": "HORSE A", "cote": 12.5}),
        # Different keys
        ({"number": "2", "horse": "HORSE B", "odds": 5.0}, {"num": "2", "name": "HORSE B", "cote": 5.0, "odds": 5.0}),
        ({"id": 3, "label": "HORSE C", "price": "2.3"}, {"num": "3", "name": "HORSE C", "id": "3", "cote": 2.3}),
        # Nested odds
        ({"num": 4, "name": "HORSE D", "odds": {"place": "3,3"}}, {"num": "4", "name": "HORSE D", "odds_place": 3.3}),
        ({"num": 5, "name": "HORSE E", "market": {"place": {"5": 4.0}}}, {"num": "5", "name": "HORSE E", "odds_place": 4.0}),
        # Missing values
        ({"num": 6, "name": "HORSE F"}, {"num": "6", "name": "HORSE F"}),
        # Empty values
        ({"num": 7, "name": "HORSE G", "cote": ""}, {"num": "7", "name": "HORSE G"}),
        # Extra metadata
        ({"num": 8, "name": "HORSE H", "driver": "DRIVER H"}, {"num": "8", "name": "HORSE H", "driver": "DRIVER H"}),
        # No number
        ({"name": "HORSE I", "cote": 9.0}, None),
        # Nested odds dictionary with 'gagnant'
        ({"num": "10", "name": "HORSE J", "odds": {"gagnant": "8,0"}}, {"num": "10", "name": "HORSE J", "cote": 8.0}),
    ],
)
def test_coerce_runner_entry_variations(raw, expected):
    """Tests _coerce_runner_entry with a variety of inputs."""
    coerced = online_fetch_zeturf._coerce_runner_entry(raw)
    assert coerced == expected

