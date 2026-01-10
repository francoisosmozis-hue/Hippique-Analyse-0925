import logging
from unittest.mock import AsyncMock, patch

import pytest

from hippique_orchestrator import stats_fetcher


@pytest.fixture
def mock_storage():
    with patch("hippique_orchestrator.stats_fetcher.gcs_client") as mock:
        yield mock


@pytest.fixture
def mock_source_registry():
    with patch("hippique_orchestrator.stats_fetcher.source_registry") as mock:
        yield mock


@pytest.mark.asyncio
async def test_collect_stats_no_snapshot_metadata(mock_storage, caplog):
    """
    Test that collect_stats logs an error and returns a dummy path
    when no snapshot metadata is found.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(return_value=None)

    with caplog.at_level(logging.ERROR):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "dummy_gcs_path_for_stats"
    assert "Cannot collect stats, no snapshot found for race_id" in caplog.text
    mock_storage.get_latest_snapshot_metadata.assert_called_once_with("race_id", "H-5", None, None)
    mock_storage.load_snapshot_from_gcs.assert_not_called()
    mock_storage.save_snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_collect_stats_snapshot_metadata_no_path(mock_storage, caplog):
    """
    Test that collect_stats logs an error and returns a dummy path
    when snapshot metadata is found but without a GCS path.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(return_value={"gcs_snapshot_path": None})

    with caplog.at_level(logging.ERROR):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "dummy_gcs_path_for_stats"
    assert "Cannot collect stats, no snapshot found for race_id" in caplog.text
    mock_storage.get_latest_snapshot_metadata.assert_called_once()
    mock_storage.load_snapshot_from_gcs.assert_not_called()
    mock_storage.save_snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_collect_stats_no_runners_in_snapshot(mock_storage, caplog):
    """
    Test that collect_stats logs a warning and returns a dummy path
    when the snapshot contains no runners.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(return_value={"runners": []})

    with caplog.at_level(logging.WARNING):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "dummy_gcs_path_for_stats"
    assert "No runners found in snapshot" in caplog.text
    mock_storage.get_latest_snapshot_metadata.assert_called_once()
    mock_storage.load_snapshot_from_gcs.assert_called_once()
    mock_storage.save_snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_collect_stats_successful_run(mock_storage, mock_source_registry):
    """
    Test a successful collection of stats for multiple runners.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(
        return_value={
            "runners": [
                {"num": 1, "name": "Horse A", "jockey": "Jockey A", "entraineur": "Trainer A"},
                {"num": 2, "name": "Horse B", "jockey": "Jockey B", "entraineur": "Trainer B"},
                {
                    "num": 3,
                    "name": "Horse C",
                    "jockey": "",
                    "entraineur": "Trainer C",
                },  # Missing jockey
                {
                    "num": 4,
                    "name": "Horse D",
                    "jockey": "Jockey D",
                    "entraineur": "",
                },  # Missing trainer
            ]
        }
    )
    mock_source_registry.fetch_stats_for_runner = AsyncMock(
        side_effect=[
            {"chrono_stats": {"last_3_chrono": "1'12''0"}, "jockey_stats": {"win_rate": 25.0}, "trainer_stats": {"win_rate": 30.0}}, # Horse A
            {"chrono_stats": {"last_3_chrono": "1'15''0"}, "jockey_stats": {"win_rate": 15.0}, "trainer_stats": {"win_rate": 10.0}}, # Horse B
            {"chrono_stats": None, "jockey_stats": None, "trainer_stats": {"win_rate": 5.0}}, # Horse C (jockey, chrono missing)
            {"chrono_stats": None, "jockey_stats": {"win_rate": 20.0}, "trainer_stats": None}, # Horse D (trainer, chrono missing)
        ]
    )
    mock_storage.save_snapshot = AsyncMock(return_value="path/to/stats.json")

    result = await stats_fetcher.collect_stats(
        "race_id", "H-5", "2025-01-01", "corr_id", "trace_id"
    )

    assert result == "path/to/stats.json"
    mock_storage.get_latest_snapshot_metadata.assert_called_once()
    mock_storage.load_snapshot_from_gcs.assert_called_once()
    assert mock_source_registry.fetch_stats_for_runner.call_count == 4

    # Check save_snapshot payload (simplified check)
    args, _ = mock_storage.save_snapshot.call_args
    _, _, _, payload, _, _ = args
    assert payload["race_doc_id"] == "race_id"
    assert payload["phase"] == "H-5"
    assert len(payload["rows"]) == 4
    # With this mock setup:
    # Horse A: chrono, jockey, trainer -> covered
    # Horse B: chrono, jockey, trainer -> covered
    # Horse C: trainer -> covered (jockey skipped, chrono None)
    # Horse D: jockey -> covered (trainer skipped, chrono None)
    # So all 4 runners have at least one stat.
    assert payload["coverage"] == 1.0


@pytest.mark.asyncio
async def test_collect_stats_error_fetching_chrono(mock_storage, mock_source_registry, caplog):
    """
    Test that an error during chrono stats fetching is logged but does not stop the process.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(
        return_value={
            "runners": [
                {"num": 1, "name": "Horse A", "jockey": "Jockey A", "entraineur": "Trainer A"}
            ]
        }
    )
    mock_source_registry.get_chrono_stats = AsyncMock(side_effect=Exception("Chrono error"))
    mock_source_registry.get_jockey_trainer_stats = AsyncMock(return_value={"win_rate": 20.0})
    mock_storage.save_snapshot = AsyncMock(return_value="path/to/stats.json")

    with caplog.at_level(logging.ERROR):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "path/to/stats.json"
    assert "Error fetching chrono stats for Horse A: Chrono error" in caplog.text
    assert (
        mock_source_registry.get_jockey_trainer_stats.call_count == 2
    )  # Once for jockey, once for trainer
    mock_storage.save_snapshot.assert_called_once()


@pytest.mark.asyncio
async def test_collect_stats_error_fetching_jockey_trainer(
    mock_storage, mock_source_registry, caplog
):
    """
    Test that an error during jockey/trainer stats fetching is logged but does not stop the process.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(
        return_value={
            "runners": [
                {"num": 1, "name": "Horse A", "jockey": "Jockey A", "entraineur": "Trainer A"}
            ]
        }
    )
    mock_source_registry.get_chrono_stats = AsyncMock(return_value={"last_3_chrono": "1'10''0"})
    mock_source_registry.get_jockey_trainer_stats = AsyncMock(
        side_effect=Exception("Jockey/Trainer error")
    )
    mock_storage.save_snapshot = AsyncMock(return_value="path/to/stats.json")

    with caplog.at_level(logging.ERROR):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "path/to/stats.json"
    assert "Error fetching jockey stats for Jockey A: Jockey/Trainer error" in caplog.text
    mock_source_registry.get_chrono_stats.assert_called_once()
    assert (
        mock_source_registry.get_jockey_trainer_stats.call_count == 2
    )  # Once for jockey, once for trainer
    mock_storage.save_snapshot.assert_called_once()


@pytest.mark.asyncio
async def test_collect_stats_save_snapshot_failure(mock_storage, mock_source_registry, caplog):
    """
    Test that a critical error is logged and dummy path returned when saving snapshot fails.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(
        return_value={
            "runners": [
                {"num": 1, "nom": "Horse A", "jockey": "Jockey A", "entraineur": "Trainer A"}
            ]
        }
    )
    mock_source_registry.get_chrono_stats = AsyncMock(return_value={"last_3_chrono": "1'10''0"})
    mock_source_registry.get_jockey_trainer_stats = AsyncMock(return_value={"win_rate": 20.0})
    mock_storage.save_snapshot = AsyncMock(side_effect=Exception("GCS save error"))

    with caplog.at_level(logging.CRITICAL):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "dummy_gcs_path_for_stats"
    assert "CRITICAL: Failed to save stats snapshot to GCS: GCS save error" in caplog.text
    mock_storage.save_snapshot.assert_called_once()


@pytest.mark.asyncio
async def test_collect_stats_missing_jockey_trainer_names(
    mock_storage, mock_source_registry, caplog
):
    """
    Test that collect_stats handles runners with missing jockey or trainer names gracefully.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(
        return_value={
            "runners": [
                {"num": 1, "name": "Horse A"},  # No jockey or trainer
                {"num": 2, "name": "Horse B", "jockey": "Jockey B"},  # No trainer
                {"num": 3, "name": "Horse C", "entraineur": "Trainer C"},  # No jockey
            ]
        }
    )
    mock_source_registry.get_chrono_stats = AsyncMock(return_value={"last_3_chrono": "1'10''0"})
    mock_source_registry.get_jockey_trainer_stats = AsyncMock(return_value={"win_rate": 20.0})
    mock_storage.save_snapshot = AsyncMock(return_value="path/to/stats.json")

    with caplog.at_level(logging.WARNING):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "path/to/stats.json"
    # No specific warnings are expected from stats_fetcher for missing jockey/trainer
    # as fetch_stats_for_runner is expected to handle that gracefully or individual
    # stat fetchers might log warnings.

    # Ensure get_jockey_trainer_stats is called only when names are present
    mock_source_registry.get_jockey_trainer_stats.assert_any_call("Jockey B", "jockey")
    mock_source_registry.get_jockey_trainer_stats.assert_any_call("Trainer C", "entraineur")
    assert (
        mock_source_registry.get_jockey_trainer_stats.call_count == 2
    )  # 1 for Jockey B, 1 for Trainer C


@pytest.mark.asyncio
async def test_collect_stats_runner_without_num_or_nom(mock_storage, mock_source_registry, caplog):
    """
    Test that collect_stats skips runners if 'num' or 'nom' are missing.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(
        return_value={
            "runners": [
                {"name": "Horse A", "jockey": "Jockey A", "entraineur": "Trainer A"},  # Missing num
                {"num": 2, "jockey": "Jockey B", "entraineur": "Trainer B"},  # Missing name
                {
                    "num": 3,
                    "name": "Horse C",
                    "jockey": "Jockey C",
                    "entraineur": "Trainer C",
                },  # Valid runner
            ]
        }
    )
    mock_source_registry.get_chrono_stats = AsyncMock(return_value={"last_3_chrono": "1'10''0"})
    mock_source_registry.get_jockey_trainer_stats = AsyncMock(return_value={"win_rate": 20.0})
    mock_storage.save_snapshot = AsyncMock(return_value="path/to/stats.json")

    result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "path/to/stats.json"
    # Only Horse C should trigger calls
    mock_source_registry.get_chrono_stats.assert_called_once_with(horse_name="Horse C")
    mock_source_registry.get_jockey_trainer_stats.assert_any_call("Jockey C", "jockey")
    mock_source_registry.get_jockey_trainer_stats.assert_any_call("Trainer C", "entraineur")
    assert mock_source_registry.get_jockey_trainer_stats.call_count == 2

    args, _ = mock_storage.save_snapshot.call_args
    _, _, _, payload, _, _ = args
    assert len(payload["rows"]) == 1  # Only one runner should have been processed


@pytest.mark.asyncio
async def test_collect_stats_get_chrono_stats_returns_none(
    mock_storage, mock_source_registry, caplog
):
    """
    Test that collect_stats logs a warning when get_chrono_stats returns None.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(
        return_value={
            "runners": [
                {"num": 1, "name": "Horse A", "jockey": "Jockey A", "entraineur": "Trainer A"}
            ]
        }
    )
    mock_source_registry.get_chrono_stats = AsyncMock(return_value=None)
    mock_source_registry.get_jockey_trainer_stats = AsyncMock(return_value={"win_rate": 20.0})
    mock_storage.save_snapshot = AsyncMock(return_value="path/to/stats.json")

    with caplog.at_level(logging.WARNING):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "path/to/stats.json"
    assert "Could not fetch chrono stats for Horse A" in caplog.text
    mock_source_registry.get_chrono_stats.assert_called_once()
    assert mock_source_registry.get_jockey_trainer_stats.call_count == 2
    mock_storage.save_snapshot.assert_called_once()


@pytest.mark.asyncio
async def test_collect_stats_get_jockey_stats_returns_none(
    mock_storage, mock_source_registry, caplog
):
    """
    Test that collect_stats logs a warning when get_jockey_trainer_stats returns None for jockey.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(
        return_value={
            "runners": [
                {"num": 1, "name": "Horse A", "jockey": "Jockey A", "entraineur": "Trainer A"}
            ]
        }
    )
    mock_source_registry.get_chrono_stats = AsyncMock(return_value={"last_3_chrono": "1'10''0"})
    mock_source_registry.get_jockey_trainer_stats = AsyncMock(
        side_effect=[None, {"win_rate": 20.0}]
    )  # Jockey None, Trainer Success
    mock_storage.save_snapshot = AsyncMock(return_value="path/to/stats.json")

    with caplog.at_level(logging.WARNING):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "path/to/stats.json"
    assert "Could not fetch jockey stats for Jockey A" in caplog.text
    mock_source_registry.get_jockey_trainer_stats.assert_any_call("Jockey A", "jockey")
    mock_source_registry.get_jockey_trainer_stats.assert_any_call("Trainer A", "entraineur")
    assert mock_source_registry.get_jockey_trainer_stats.call_count == 2
    mock_storage.save_snapshot.assert_called_once()


@pytest.mark.asyncio
async def test_collect_stats_get_trainer_stats_returns_none(
    mock_storage, mock_source_registry, caplog
):
    """
    Test that collect_stats logs a warning when get_jockey_trainer_stats returns None for trainer.
    """
    mock_storage.get_latest_snapshot_metadata = AsyncMock(
        return_value={"gcs_snapshot_path": "path/to/snapshot.json"}
    )
    mock_storage.load_snapshot_from_gcs = AsyncMock(
        return_value={
            "runners": [
                {"num": 1, "name": "Horse A", "jockey": "Jockey A", "entraineur": "Trainer A"}
            ]
        }
    )
    mock_source_registry.get_chrono_stats = AsyncMock(return_value={"last_3_chrono": "1'10''0"})
    mock_source_registry.get_jockey_trainer_stats = AsyncMock(
        side_effect=[{"win_rate": 20.0}, None]
    )  # Jockey Success, Trainer None
    mock_storage.save_snapshot = AsyncMock(return_value="path/to/stats.json")

    with caplog.at_level(logging.WARNING):
        result = await stats_fetcher.collect_stats("race_id", "H-5", "2025-01-01")

    assert result == "path/to/stats.json"
    assert "Could not fetch trainer stats for Trainer A" in caplog.text
    mock_source_registry.get_jockey_trainer_stats.assert_any_call("Jockey A", "jockey")
    mock_source_registry.get_jockey_trainer_stats.assert_any_call("Trainer A", "entraineur")
    assert mock_source_registry.get_jockey_trainer_stats.call_count == 2
    mock_storage.save_snapshot.assert_called_once()
