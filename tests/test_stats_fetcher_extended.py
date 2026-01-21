import logging
from unittest.mock import AsyncMock

import pytest

from hippique_orchestrator import stats_fetcher
from hippique_orchestrator.providers.interface import ProviderInterface


@pytest.fixture
def mock_storage(mocker):
    """Mocks the gcs_client and its async methods used by stats_fetcher."""
    mock = mocker.patch("hippique_orchestrator.stats_fetcher.gcs_client")
    mock.get_latest_snapshot_metadata = AsyncMock()
    mock.load_snapshot_from_gcs = AsyncMock()
    mock.save_snapshot = AsyncMock()
    return mock


@pytest.fixture
def mock_active_provider(mocker):
    """Mocks the active provider obtained from the ProviderRegistry."""
    # Mock the get_active_provider function from the registry
    mock_get_active_provider_fn = mocker.patch(
        "hippique_orchestrator.stats_fetcher.source_registry.get_primary_snapshot_provider", autospec=True
    )    # Create a mock provider instance that get_active_provider will return
    mock_provider_instance = mocker.create_autospec(ProviderInterface)
    mock_provider_instance.get_name.return_value = "mock_stat_provider"
    mock_provider_instance.fetch_stats_for_runner = AsyncMock(return_value={})

    mock_get_active_provider_fn.return_value = mock_provider_instance
    return mock_provider_instance


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
async def test_collect_stats_successful_run(mock_storage, mock_active_provider):
    """Test a successful run of collect_stats."""
    mock_storage.get_latest_snapshot_metadata.return_value = {"gcs_snapshot_path": "path/to/snapshot.json"}
    mock_storage.load_snapshot_from_gcs.return_value = {
        "runners": [
            {"num": 1, "name": "Horse A", "discipline": "Trot Attelé"},
            {"num": 2, "name": "Horse B", "discipline": "Trot Monté"},
        ],
        "discipline": "Trot Attelé", # Ensure discipline is in snapshot_data
    }
    mock_active_provider.fetch_stats_for_runner.side_effect = [
        {"chrono": "good"},
        {"jockey": "top"},
    ]
    await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert mock_active_provider.fetch_stats_for_runner.call_count == 2
    mock_active_provider.fetch_stats_for_runner.assert_any_call(
        runner_name="Horse A",
        discipline="Trot Attelé",
        runner_data={"num": 1, "name": "Horse A", "discipline": "Trot Attelé"},
        correlation_id=None,
        trace_id=None,
    )
    mock_active_provider.fetch_stats_for_runner.assert_any_call(
        runner_name="Horse B",
        discipline="Trot Attelé", # Discipline from snapshot_data should override runner_data if present
        runner_data={"num": 2, "name": "Horse B", "discipline": "Trot Monté"},
        correlation_id=None,
        trace_id=None,
    )
    mock_storage.save_snapshot.assert_called_once()
    saved_data = mock_storage.save_snapshot.call_args[0][3]["rows"]
    assert len(saved_data) == 2
    assert saved_data[0] == {"num": 1, "name": "Horse A", "chrono": "good"}
    assert saved_data[1] == {"num": 2, "name": "Horse B", "jockey": "top"}


@pytest.mark.asyncio
async def test_collect_stats_no_active_provider(mock_storage, mocker, caplog):
    """Test that collect_stats handles the case where no active provider is found."""
    mocker.patch(
        "hippique_orchestrator.stats_fetcher.source_registry.get_primary_snapshot_provider",
        return_value=None,
    )
    mock_storage.get_latest_snapshot_metadata.return_value = {"gcs_snapshot_path": "path/to/snapshot.json"}
    mock_storage.load_snapshot_from_gcs.return_value = {"runners": [{"num": 1, "name": "Horse A"}]}

    with caplog.at_level(logging.ERROR):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")
        assert any("No primary snapshot provider available for stats collection." in record.message for record in caplog.records)
    assert result == "dummy_gcs_path_for_stats"
    mock_storage.save_snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_collect_stats_error_fetching_stats(mock_storage, mock_active_provider, caplog):
    """Test that an error during stats fetching is logged and the process stops."""
    mock_storage.get_latest_snapshot_metadata.return_value = {"gcs_snapshot_path": "path/to/snapshot.json"}
    mock_storage.load_snapshot_from_gcs.return_value = {
        "runners": [{"num": 1, "name": "Horse A"}],
        "discipline": "Trot Attelé",
    }
    mock_active_provider.fetch_stats_for_runner.side_effect = Exception("Provider error")

    with pytest.raises(Exception, match="Provider error"):
        await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert "Fetching stats for runner Horse A" in caplog.text


@pytest.mark.asyncio
async def test_collect_stats_runner_without_num_or_name(mock_storage, mock_active_provider, caplog):
    """Test that runners with missing 'num' or 'name' are skipped."""
    mock_storage.get_latest_snapshot_metadata.return_value = {"gcs_snapshot_path": "path/to/snapshot.json"}
    mock_storage.load_snapshot_from_gcs.return_value = {
        "runners": [
            {"name": "Horse A"},  # Missing num
            {"num": 2},          # Missing name
            {"num": 3, "name": "Horse C"},
        ],
        "discipline": "Trot Attelé",
    }
    with caplog.at_level(logging.WARNING):
        await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")
        assert "Skipping runner due to missing num or name" in caplog.text

    assert mock_active_provider.fetch_stats_for_runner.call_count == 1
    mock_active_provider.fetch_stats_for_runner.assert_called_once_with(
        runner_name="Horse C",
        discipline="Trot Attelé",
        runner_data={"num": 3, "name": "Horse C"},
        correlation_id=None,
        trace_id=None,
    )
