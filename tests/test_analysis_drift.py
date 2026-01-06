"""
Test the analysis pipeline's ability to handle H-30/H-5 drift.
"""

import json
import asyncio
import yaml
import pytest

from hippique_orchestrator import analysis_pipeline

# Sample odds data showing a significant drift for horse #5
H30_RUNNERS = [
    {"num": "1", "nom": "Horse A", "odds_place": 3.0},
    {"num": "5", "nom": "Horse B", "odds_place": 8.0},  # Original odds
    {"num": "8", "nom": "Horse C", "odds_place": 12.0},
]

H5_RUNNERS = [
    {"num": "1", "nom": "Horse A", "odds_place": 3.2},
    {"num": "5", "nom": "Horse B", "odds_place": 5.5},  # Odds have steamed (decreased)
    {"num": "8", "nom": "Horse C", "odds_place": 12.0},
]

# Minimal snapshot structure
H30_SNAPSHOT = {"race_name": "Test Race", "runners": H30_RUNNERS}
H5_SNAPSHOT = {"race_name": "Test Race", "runners": H5_RUNNERS}

# Minimal GPI config
GPI_CONFIG_YAML = """
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


@pytest.mark.asyncio
async def test_drift_is_detected_and_applied(mocker):
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

    # Mock other dependencies that are called
    mocker.patch("hippique_orchestrator.analysis_pipeline.collect_stats", return_value="stats.json")
    mocker.patch("hippique_orchestrator.data_source.fetch_race_details", return_value=H5_SNAPSHOT)

    # 2. Run the analysis for the H-5 phase
    analysis_result = await analysis_pipeline.run_analysis_for_phase(
        course_url="http://example.com/race/1",
        phase="H-5",
        date="2025-01-01",
        race_doc_id="2025-01-01_R1C1",
    )

    # 3. Assertions
    assert analysis_result is not None
    assert analysis_result["gpi_decision"] is not None

    # Check that the H-30 snapshot was found
    mock_gcs_client.list_files.assert_called_with("data/2025-01-01_R1C1/snapshots/")

    # Check the analysis table for the horse that had drift
    market_table = analysis_result.get("tickets_analysis", {}).get("market_analysis_table", [])
    assert len(market_table) > 0, "Market analysis table should not be empty"

    horse_5_analysis = next((r for r in market_table if r.get("num") == "5"), None)

    assert horse_5_analysis is not None, "Horse #5 should be in the analysis table"
    assert horse_5_analysis["drift_status"] == "Steam", (
        "Drift status for horse #5 should be 'Steam'"
    )
    assert horse_5_analysis["drift_percent"] < 0, "Drift percentage should be negative for steam"


@pytest.mark.asyncio
async def test_pipeline_raises_if_doc_id_missing(mocker):
    """
    Given no race_doc_id is provided and the URL is invalid,
    When run_analysis_for_phase is called,
    Then it should raise a ValueError.
    """
    mocker.patch(
        "hippique_orchestrator.analysis_pipeline.firestore_client.get_doc_id_from_url",
        return_value=None,
    )

    with pytest.raises(ValueError, match="Could not determine race_doc_id"):
        await analysis_pipeline.run_analysis_for_phase(
            course_url="invalid-url", phase="H-5", date="2025-01-01"
        )


@pytest.mark.asyncio
async def test_pipeline_abstains_if_snapshot_is_empty(mocker):
    """
    Given the snapshot fetch returns no data,
    When the analysis pipeline runs,
    Then it should return an 'abstention' decision.
    """
    # Mock the fetch and save step to return None
    mocker.patch(
        "hippique_orchestrator.analysis_pipeline._fetch_and_save_snapshot",
        return_value=(None, None),
    )

    result = await analysis_pipeline.run_analysis_for_phase(
        course_url="http://example.com/race/1",
        phase="H-5",
        date="2025-01-01",
        race_doc_id="2025-01-01_R1C1",
    )

    assert result["status"] == "abstention"
    assert result["gpi_decision"] == "ABSTENTION_NO_DATA"
    assert "snapshot missing or runners empty" in result["abstention_raisons"][0]


@pytest.mark.asyncio
async def test_pipeline_handles_generic_exception(mocker):
    """
    Given an unexpected error occurs during snapshot fetching,
    When the analysis pipeline runs,
    Then it should return an 'error' status and log the exception.
    """
    mocker.patch(
        "hippique_orchestrator.analysis_pipeline._fetch_and_save_snapshot",
        side_effect=Exception("Unexpected GCS error"),
    )

    result = await analysis_pipeline.run_analysis_for_phase(
        course_url="http://example.com/race/1",
        phase="H-5",
        date="2025-01-01",
        race_doc_id="2025-01-01_R1C1",
    )

    assert result["status"] == "error"
    assert result["gpi_decision"] == "error_pipeline_failure"
    assert "Unexpected GCS error" in result["error_message"]
