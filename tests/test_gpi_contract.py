import datetime
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from hippique_orchestrator.data_contract import RaceSnapshotNormalized, RaceData, RunnerData, RunnerStats, calculate_quality_score, compute_odds_place_ratio
from hippique_orchestrator.scripts.online_fetch_zeturf import _fallback_parse_html as parse_zeturf_html

FIXTURE_DIR = Path(__file__).parent / 'fixtures'

@pytest.fixture
def zeturf_race_html_content() -> str:
    """Provides the HTML content of the ZEturf race fixture."""
    fixture_path = FIXTURE_DIR / 'zeturf_race.html'
    if not fixture_path.exists():
        pytest.fail(f"Fixture file not found: {fixture_path}")
    return fixture_path.read_text(encoding='utf-8')

def test_gpi_contract_validation(zeturf_race_html_content):
    """
    Tests the GPI contract validation using a ZEturf fixture,
    ensuring quality score and odds place ratio meet thresholds.
    """
    # Parse the ZEturf HTML content
    raw_parsed_data = parse_zeturf_html(zeturf_race_html_content)

    assert raw_parsed_data is not None, "Failed to parse ZEturf fixture."
    assert "runners" in raw_parsed_data, "Parsed data missing 'runners' key."
    assert raw_parsed_data["runners"], "No runners found in parsed data."

    # Manually construct RaceSnapshotNormalized for validation purposes
    runners = []
    for item in raw_parsed_data.get("runners", []):
        runners.append(RunnerData(
            num=int(item["num"]),
            nom=item["name"],
            odds_place=float(item["odds_place"]) if item.get("odds_place") else None,
            odds_win=float(item["cote"]) if item.get("cote") else None,
            musique="1p2p", # Dummy value for quality score
            stats=RunnerStats(driver_rate=0.5) # Dummy value for quality score
        ))

    race_data = RaceData(
        date=datetime.date.fromisoformat("2026-01-16"), # Use date from fixture
        rc_label="R1C1",
        discipline="Attelé", # Use discipline from fixture
        num_partants=raw_parsed_data.get("partants", len(runners)),
        url="http://example.com/race_url"
    )
    
    snapshot = RaceSnapshotNormalized(
        race_id="2026-01-16_R1C1",
        race=race_data,
        runners=runners,
        source_snapshot="Zeturf",
        meta={
            "partants": raw_parsed_data.get("partants", len(runners)),
            "discipline": raw_parsed_data.get("discipline", "Attelé"),
            "phase": "H5",
            "meeting": raw_parsed_data.get("meeting", "Vincennes"),
            "date": raw_parsed_data.get("date", "2026-01-16"),
        }
    )

    # Calculate Quality Score
    quality_score_result = calculate_quality_score(snapshot)
    assert quality_score_result["score"] >= 0.85, f"Quality score {quality_score_result['score']} is below required 0.85"
    assert quality_score_result["status"] == "OK", f"Quality status is {quality_score_result['status']}, expected OK"

    # Calculate Odds Place Ratio
    place_odds = {str(runner.num): runner.odds_place for runner in snapshot.runners if runner.odds_place is not None}
    partants = snapshot.meta["partants"]
    odds_place_ratio = compute_odds_place_ratio(place_odds, partants)
    assert odds_place_ratio >= 0.90, f"Odds place ratio {odds_place_ratio} is below required 0.90"

