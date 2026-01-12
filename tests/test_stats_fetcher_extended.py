import logging
from unittest.mock import AsyncMock
import pytest
from hippique_orchestrator import stats_fetcher

@pytest.fixture
def mock_storage(mocker):
    """Mocks the gcs_client and its async methods used by stats_fetcher."""
    mock = mocker.patch("hippique_orchestrator.stats_fetcher.gcs_client")
    mock.get_latest_snapshot_metadata = AsyncMock()
    mock.load_snapshot_from_gcs = AsyncMock()
    mock.save_snapshot = AsyncMock()
    return mock

@pytest.fixture
def mock_source_registry(mocker):
    """Mocks the source_registry instance and its async methods."""
    mock_registry = mocker.patch("hippique_orchestrator.stats_fetcher.source_registry")
    mock_registry.fetch_stats_for_runner = AsyncMock(return_value={})
    return mock_registry

@pytest.mark.asyncio
async def test_collect_stats_no_snapshot_metadata(mock_storage, caplog):
    """Test that collect_stats aborts if no snapshot metadata is found."""
    mock_storage.get_latest_snapshot_metadata.return_value = None
    with caplog.at_level(logging.ERROR):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")
        assert "Cannot collect stats, no snapshot found" in caplog.text
    assert result == "dummy_gcs_path_for_stats"

@pytest.mark.asyncio
async def test_collect_stats_no_runners_in_snapshot(mock_storage, caplog):
    """Test that collect_stats aborts if the snapshot contains no runners."""
    mock_storage.get_latest_snapshot_metadata.return_value = {"gcs_snapshot_path": "path/to/snapshot.json"}
    mock_storage.load_snapshot_from_gcs.return_value = {"runners": []}
    with caplog.at_level(logging.WARNING):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")
        assert "No runners found in snapshot" in caplog.text
    assert result == "dummy_gcs_path_for_stats"

@pytest.mark.asyncio
async def test_collect_stats_successful_run(mock_storage, mock_source_registry):
    """Test a successful run of collect_stats."""
    mock_storage.get_latest_snapshot_metadata.return_value = {"gcs_snapshot_path": "path/to/snapshot.json"}
    mock_storage.load_snapshot_from_gcs.return_value = {
        "runners": [
            {"num": 1, "name": "Horse A"},
            {"num": 2, "name": "Horse B"},
        ]
    }
    mock_source_registry.fetch_stats_for_runner.side_effect = [
        {"chrono": "good"},
        {"jockey": "top"},
    ]
    await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert mock_source_registry.fetch_stats_for_runner.call_count == 2
    mock_storage.save_snapshot.assert_called_once()
    saved_data = mock_storage.save_snapshot.call_args[0][3]["rows"]
    assert len(saved_data) == 2
    assert saved_data[0] == {"num": 1, "name": "Horse A", "chrono": "good"}
    assert saved_data[1] == {"num": 2, "name": "Horse B", "jockey": "top"}

@pytest.mark.asyncio

async def test_collect_stats_error_fetching_stats(mock_storage, mock_source_registry, caplog):

    """Test that an error during stats fetching is logged and the process stops."""

    mock_storage.get_latest_snapshot_metadata.return_value = {"gcs_snapshot_path": "path/to/snapshot.json"}

    mock_storage.load_snapshot_from_gcs.return_value = {

        "runners": [{"num": 1, "name": "Horse A"}]

    }

    mock_source_registry.fetch_stats_for_runner.side_effect = Exception("Provider error")



    with pytest.raises(Exception, match="Provider error"):

        await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")



    assert "Fetching stats for runner Horse A" in caplog.text

@pytest.mark.asyncio
async def test_collect_stats_runner_without_num_or_name(mock_storage, mock_source_registry, caplog):
    """Test that runners with missing 'num' or 'name' are skipped."""
    mock_storage.get_latest_snapshot_metadata.return_value = {"gcs_snapshot_path": "path/to/snapshot.json"}
    mock_storage.load_snapshot_from_gcs.return_value = {
        "runners": [
            {"name": "Horse A"},
            {"num": 2},
            {"num": 3, "name": "Horse C"},
        ]
    }
    with caplog.at_level(logging.WARNING):
        await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")
        assert "Skipping runner due to missing num or name" in caplog.text

    assert mock_source_registry.fetch_stats_for_runner.call_count == 1
    mock_source_registry.fetch_stats_for_runner.assert_called_once_with(
        runner_name="Horse C",
        discipline="unknown",
        runner_data={"num": 3, "name": "Horse C"},
        correlation_id=None,
        trace_id=None,
    )