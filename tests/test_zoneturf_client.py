import pytest
from hippique_orchestrator import zoneturf_client

@pytest.fixture
def zeturf_race_html():
    with open("tests/fixtures/zeturf_race.html", "r", encoding="utf-8") as f:
        return f.read()

def test_parse_race_data(zeturf_race_html):
    soup = zoneturf_client.parse_html(zeturf_race_html)
    race_data = zoneturf_client.parse_race_data(soup)
    
    assert "runners" in race_data
    # There are 14 runners in the HTML, but one is a non-partant.
    # The current logic parses all of them. Let's expect 14 for now.
    # We will filter non-partants later if needed.
    # After inspecting the code, the non-partant has no odds, so it will be filtered by the quality score.
    # Let's check the number of runners parsed.
    assert len(race_data["runners"]) == 14

    first_runner = race_data["runners"][0]
    assert first_runner["name"] == "KENJY BEL"
    assert first_runner["record"] == "1'15\"0"
    assert first_runner["win_rate"] is None
    assert first_runner["place_rate"] is None
    assert first_runner["odds"] == 74.9
    assert first_runner["place_odds"] == 12.2
def test_quality_and_ratios(zeturf_race_html):
    soup = zoneturf_client.parse_html(zeturf_race_html)
    snapshot = zoneturf_client.parse_race_data(soup)

    quality_score = zoneturf_client.calculate_quality_score(snapshot)
    odds_place_ratio = zoneturf_client.calculate_odds_place_ratio(snapshot)

    # 13 runners have full data, 1 is non-partant (NP) with no odds.
    # So 13/14 runners should have the required data.
    # However, the calculate_quality_score function considers a runner valid if it has all keys
    # The non-partant has None for odds and place_odds, so it will not be valid.
    # So, 13 out of 14 runners are valid.
    assert quality_score == 13/14

    # 13 runners have odds, and all of them have place_odds
    assert odds_place_ratio == 1.0
