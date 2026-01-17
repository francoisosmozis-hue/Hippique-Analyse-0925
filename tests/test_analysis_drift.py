"""
Test the analysis pipeline's ability to handle H-30/H-5 drift.
"""

import json
from unittest.mock import AsyncMock

import pytest

from hippique_orchestrator import analysis_pipeline
from hippique_orchestrator.data_contract import Race
import datetime

# Sample odds data showing a significant drift for horse #5
H30_RUNNERS = [
    {"num": 1, "nom": "Horse A", "odds_place": 3.0},
    {"num": 5, "nom": "Horse B", "odds_place": 8.0},  # Original odds
    {"num": 8, "nom": "Horse C", "odds_place": 12.0},
]

H5_RUNNERS = [
    {"num": 1, "nom": "Horse A", "odds_place": 3.2},
    {"num": 5, "nom": "Horse B", "odds_place": 5.5},  # Odds have steamed (decreased)
    {"num": 8, "nom": "Horse C", "odds_place": 12.0},
]

# Minimal snapshot structure adhering to RaceSnapshotNormalized
H30_SNAPSHOT = {
    "race": {"date": "2025-01-01", "race_id": "R1C1", "hippodrome": "TEST_HIPPODROME", "country_code": "FR", "discipline": "Plat"},
    "runners": H30_RUNNERS,
    "source_snapshot": "TestH30Provider",
}
H5_SNAPSHOT = {
    "race": {"date": "2025-01-01", "race_id": "R1C1", "hippodrome": "TEST_HIPPODROME", "country_code": "FR", "discipline": "Plat"},
    "runners": H5_RUNNERS,
    "source_snapshot": "TestH5Provider",
}

# Minimal GPI config
GPI_CONFIG_YAML = """
budget: 5
weights:
  base: {}
  horse_stats: {}
adjustments:
  chrono: {}
  drift: {}
  volatility: {}
tickets:
  sp_dutching:
    budget_ratio: 0.6
    odds_range: [5.0, 20.0]
    legs_max: 5
    legs_min: 2
    kelly_frac: 0.5
  exotics: {}
roi_min_global: 0.05
roi_min_sp: 0.05
overround_max_exotics: 1.30
ev_min_combo: 0.10
payout_min_combo: 2.0
"""


H5_STATS = {
    "rows": [
        {"num": 1, "driver_rate": 0.2},
        {"num": 5, "driver_rate": 0.15},  # Example stat
        {"num": 8, "driver_rate": 0.1},
    ]
}

@pytest.fixture
def mock_programme_provider(mocker):
    """Mocks programme_provider.get_race_details to return a complete Race object."""
    mock_race_object = Race(
        date=datetime.date(2025, 1, 1),
        reunion_id=1,
        race_id="R1C1",
        course_id=1,
        hippodrome="TEST_HIPPODROME",
        country_code="FR",
        url="http://example.com/race/1",
    )
    mock = mocker.patch(
        "hippique_orchestrator.analysis_pipeline.programme_provider.get_race_details",
        return_value=mock_race_object,
    )
    return mock


@pytest.mark.asyncio
async def test_drift_is_detected_and_applied(mocker, mock_programme_provider):
    """
    Ensures that when an H-5 analysis is run, it finds the H-30 snapshot,
    loads it, and the final analysis shows a non-stable drift status.
    """
    # 1. Mock GCS client
    mock_gcs_client = mocker.patch("hippique_orchestrator.analysis_pipeline.gcs_client")

    # Mock file listing to find the H-30 snapshot
    mock_gcs_client.list_files.return_value = ["data/R1C1/snapshots/20250101_120000_H-30.json"]

    # Mock file reading to return different content based on path
    def mock_read_file(path):
        if "_H-30.json" in path:
            return json.dumps(H30_SNAPSHOT)
        if "gpi_v52.yml" in path:
            return GPI_CONFIG_YAML
        # For the H-5 snapshot itself and stats, return the H-5 data
        return json.dumps(H5_SNAPSHOT)

    mock_gcs_client.read_file_from_gcs.side_effect = mock_read_file

    mocker.patch(
        "hippique_orchestrator.analysis_pipeline.source_registry.fetch_stats_for_runner",
        return_value={"mock_stats": "stats.json"},
    )