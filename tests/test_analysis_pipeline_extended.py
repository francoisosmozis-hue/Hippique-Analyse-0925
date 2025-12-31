from __future__ import annotations

import json
import asyncio
import yaml
import pytest
from unittest.mock import MagicMock, patch
from pytest import LogCaptureFixture

from hippique_orchestrator import analysis_pipeline, firestore_client

# Minimal snapshot structure for H-5
H5_SNAPSHOT = {"race_name": "Test Race", "runners": [{"num": "1", "nom": "Horse A", "odds_place": 3.2}]}


@pytest.mark.asyncio
async def test_find_and_load_h30_snapshot_no_snapshots_found(mocker, caplog: LogCaptureFixture):
    """
    _find_and_load_h30_snapshot should return an empty dict and log a warning
    if gcs_client.list_files returns an empty list.
    """
    mock_gcs_client = mocker.patch("hippique_orchestrator.analysis_pipeline.gcs_client")
    mock_gcs_client.list_files.return_value = []
    
    caplog.set_level("WARNING")
    result = analysis_pipeline._find_and_load_h30_snapshot("test_race_id", {})
    
    assert result == {}
    assert "No snapshots found in directory." in caplog.text
    mock_gcs_client.list_files.assert_called_once_with("data/test_race_id/snapshots/")


@pytest.mark.asyncio
async def test_find_and_load_h30_snapshot_no_h30_snapshots_found(mocker, caplog: LogCaptureFixture):
    """
    _find_and_load_h30_snapshot should return an empty dict and log a warning
    if gcs_client.list_files returns files but none are H-30.
    """
    mock_gcs_client = mocker.patch("hippique_orchestrator.analysis_pipeline.gcs_client")
    mock_gcs_client.list_files.return_value = ["data/test_race_id/snapshots/20250101_120000_H-5.json"]
    
    caplog.set_level("WARNING")
    result = analysis_pipeline._find_and_load_h30_snapshot("test_race_id", {})
    
    assert result == {}
    assert "No H-30 snapshot found for drift calculation." in caplog.text
    mock_gcs_client.list_files.assert_called_once_with("data/test_race_id/snapshots/")


@pytest.mark.asyncio
async def test_find_and_load_h30_snapshot_list_files_exception(mocker, caplog: LogCaptureFixture):
    """
    _find_and_load_h30_snapshot should return an empty dict and log an error
    if gcs_client.list_files raises an exception.
    """
    mock_gcs_client = mocker.patch("hippique_orchestrator.analysis_pipeline.gcs_client")
    mock_gcs_client.list_files.side_effect = Exception("GCS List Error")
    
    caplog.set_level("ERROR")
    result = analysis_pipeline._find_and_load_h30_snapshot("test_race_id", {})
    
    assert result == {}
    assert "Failed to find or load H-30 snapshot: GCS List Error" in caplog.text
    mock_gcs_client.list_files.assert_called_once_with("data/test_race_id/snapshots/")


@pytest.mark.asyncio
async def test_find_and_load_h30_snapshot_read_file_exception(mocker, caplog: LogCaptureFixture):
    """
    _find_and_load_h30_snapshot should return an empty dict and log an error
    if gcs_client.read_file_from_gcs raises an exception.
    """
    mock_gcs_client = mocker.patch("hippique_orchestrator.analysis_pipeline.gcs_client")
    mock_gcs_client.list_files.return_value = ["data/test_race_id/snapshots/20250101_120000_H-30.json"]
    mock_gcs_client.read_file_from_gcs.side_effect = Exception("GCS Read Error")
    
    caplog.set_level("ERROR")
    result = analysis_pipeline._find_and_load_h30_snapshot("test_race_id", {})
    
    assert result == {}
    assert "Failed to find or load H-30 snapshot: GCS Read Error" in caplog.text
    mock_gcs_client.list_files.assert_called_once_with("data/test_race_id/snapshots/")
    mock_gcs_client.read_file_from_gcs.assert_called_once_with("data/test_race_id/snapshots/20250101_120000_H-30.json")


@pytest.mark.asyncio
async def test_run_analysis_for_phase_abstains_on_empty_snapshot_from_data_source(mocker):
    """
    Given data_source.fetch_race_details returns empty or None,
    When run_analysis_for_phase is called,
    Then it should trigger the abstention logic.
    """
    mocker.patch("hippique_orchestrator.data_source.fetch_race_details", return_value={})
    mocker.patch("hippique_orchestrator.analysis_pipeline.firestore_client.get_doc_id_from_url", return_value="2025-01-01_R1C1")
    mocker.patch("hippique_orchestrator.analysis_pipeline.gcs_client.save_json_to_gcs") # Mock to prevent actual GCS calls

    result = await analysis_pipeline.run_analysis_for_phase(
        course_url="http://example.com/race/1",
        phase="H-5",
        date="2025-01-01",
        race_doc_id="2025-01-01_R1C1"
    )

    assert result["status"] == "abstention"
    assert "snapshot missing or runners empty" in result["abstention_raisons"][0]
    analysis_pipeline.gcs_client.save_json_to_gcs.assert_not_called()

@pytest.mark.asyncio
async def test_run_analysis_for_phase_abstains_on_snapshot_with_no_runners(mocker):
    """
    Given data_source.fetch_race_details returns snapshot data but with no runners,
    When run_analysis_for_phase is called,
    Then it should trigger the abstention logic.
    """
    mocker.patch("hippique_orchestrator.data_source.fetch_race_details", return_value={"race_name": "Test Race", "runners": []})
    mocker.patch("hippique_orchestrator.analysis_pipeline.firestore_client.get_doc_id_from_url", return_value="2025-01-01_R1C1")
    mocker.patch("hippique_orchestrator.analysis_pipeline.gcs_client.save_json_to_gcs") # Mock to prevent actual GCS calls

    result = await analysis_pipeline.run_analysis_for_phase(
        course_url="http://example.com/race/1",
        phase="H-5",
        date="2025-01-01",
        race_doc_id="2025-01-01_R1C1"
    )

    assert result["status"] == "abstention"
    assert "snapshot missing or runners empty" in result["abstention_raisons"][0]
    analysis_pipeline.gcs_client.save_json_to_gcs.assert_not_called()
