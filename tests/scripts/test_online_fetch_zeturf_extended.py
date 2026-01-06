import json
import re
from pathlib import Path

import pytest

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
    modified_html = zeturf_course_html.replace('<span class="cote">6.5</span>', "", 1)
    # Also remove the script fallback
    modified_html = re.sub(r"cotesInfos: \{.*\}", "cotesInfos: {}", modified_html)

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
        (
            {"num": "1", "name": "HORSE A", "cote": "12,5"},
            {"num": "1", "name": "HORSE A", "cote": 12.5},
        ),
        # Different keys
        (
            {"number": "2", "horse": "HORSE B", "odds": 5.0},
            {"num": "2", "name": "HORSE B", "cote": 5.0, "odds": 5.0},
        ),
        (
            {"id": 3, "label": "HORSE C", "price": "2.3"},
            {"num": "3", "name": "HORSE C", "id": "3", "cote": 2.3},
        ),
        # Nested odds
        (
            {"num": 4, "name": "HORSE D", "odds": {"place": "3,3"}},
            {"num": "4", "name": "HORSE D", "odds_place": 3.3},
        ),
        (
            {"num": 5, "name": "HORSE E", "market": {"place": {"5": 4.0}}},
            {"num": "5", "name": "HORSE E", "odds_place": 4.0},
        ),
        # Missing values
        ({"num": 6, "name": "HORSE F"}, {"num": "6", "name": "HORSE F"}),
        # Empty values
        ({"num": 7, "name": "HORSE G", "cote": ""}, {"num": "7", "name": "HORSE G"}),
        # Extra metadata
        (
            {"num": 8, "name": "HORSE H", "driver": "DRIVER H"},
            {"num": "8", "name": "HORSE H", "driver": "DRIVER H"},
        ),
        # No number
        ({"name": "HORSE I", "cote": 9.0}, None),
        # Nested odds dictionary with 'gagnant'
        (
            {"num": "10", "name": "HORSE J", "odds": {"gagnant": "8,0"}},
            {"num": "10", "name": "HORSE J", "cote": 8.0},
        ),
    ],
)
def test_coerce_runner_entry_variations(raw, expected):
    """Tests _coerce_runner_entry with a variety of inputs."""
    coerced = online_fetch_zeturf._coerce_runner_entry(raw)
    assert coerced == expected


def test_coerce_runner_entry_invalid_input():
    """Tests that _coerce_runner_entry returns None for non-dict inputs."""
    assert online_fetch_zeturf._coerce_runner_entry(None) is None
    assert online_fetch_zeturf._coerce_runner_entry("a string") is None
    assert online_fetch_zeturf._coerce_runner_entry(123) is None
    assert online_fetch_zeturf._coerce_runner_entry([1, 2, 3]) is None


def test_normalise_snapshot_result_merges_h30_odds(fs):
    """
    Tests that _normalise_snapshot_result correctly merges H30 odds into an H5 snapshot.
    """
    # Create a fake h30.json file
    h30_data = {
        "runners": [
            {"num": "1", "odds_win_h30": 10.0, "odds_place_h30": 2.0},
            {"num": "2", "odds_win_h30": 5.0, "odds_place_h30": 1.5},
        ]
    }
    fs.create_file("data/R1C1/h30.json", contents=json.dumps(h30_data))

    raw_snapshot = {
        "runners": [
            {"num": "1", "name": "HORSE A", "cote": 12.0},
            {"num": "2", "name": "HORSE B", "cote": 6.0},
        ]
    }

    result = online_fetch_zeturf._normalise_snapshot_result(
        raw_snapshot,
        reunion_hint="R1",
        course_hint="C1",
        phase_norm="H5",
        sources_config={},
    )

    assert len(result["runners"]) == 2
    runner1 = result["runners"][0]
    assert runner1["odds_win_h30"] == 10.0
    assert runner1["odds_place_h30"] == 2.0
    runner2 = result["runners"][1]
    assert runner2["odds_win_h30"] == 5.0
    assert runner2["odds_place_h30"] == 1.5


def test_normalise_snapshot_result_no_market():
    """
    Tests that _normalise_snapshot_result handles a raw snapshot without a 'market' dictionary.
    """
    raw_snapshot = {"runners": [{"num": "1", "name": "HORSE A", "cote": 12.0}]}

    result = online_fetch_zeturf._normalise_snapshot_result(
        raw_snapshot,
        reunion_hint="R1",
        course_hint="C1",
        phase_norm="H5",
        sources_config={},
    )

    assert "market" in result
    assert result["market"] == {
        'slots_place': 3,
        'overround_win': 0.0833,
        'overround': 0.0833,
        'overround_place': 0.0833,
    }


def test_http_get_raises_on_403(mocker):
    """
    Tests that _http_get raises a RuntimeError on a 403 status code.
    """
    mock_response = mocker.MagicMock()
    mock_response.status_code = 403
    mocker.patch("requests.get", return_value=mock_response)

    with pytest.raises(RuntimeError, match="HTTP 403 returned by http://example.com"):
        online_fetch_zeturf._http_get("http://example.com")


def test_http_get_raises_on_suspicious_html(mocker):
    """
    Tests that _http_get raises a RuntimeError on suspicious HTML content.
    """
    mock_response = mocker.MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><body>captcha</body></html>"
    mocker.patch("requests.get", return_value=mock_response)

    with pytest.raises(RuntimeError, match="Payload suspect reçu de http://example.com"):
        online_fetch_zeturf._http_get("http://example.com")
