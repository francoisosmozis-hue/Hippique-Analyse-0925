import logging
from unittest.mock import AsyncMock, patch

import pytest

from hippique_orchestrator import snapshot_manager


@pytest.fixture
def mock_build_plan_async():
    with patch(
        "hippique_orchestrator.snapshot_manager.build_plan_async", new_callable=AsyncMock
    ) as mock:
        yield mock


@pytest.fixture
def mock_run_course():
    with patch("hippique_orchestrator.snapshot_manager.run_course") as mock:
        yield mock


@pytest.mark.asyncio
async def test_write_snapshot_for_day_async_empty_plan(
    mock_build_plan_async, mock_run_course, caplog
):
    """
    Test that write_snapshot_for_day_async logs a warning and does not call run_course
     when build_plan_async returns an empty plan.
    """
    mock_build_plan_async.return_value = []

    with caplog.at_level(logging.WARNING):
        await snapshot_manager.write_snapshot_for_day_async(
            date_str="2025-01-01", phase="H-5", correlation_id="test_id"
        )

    assert "No race plan found for 2025-01-01." in caplog.text
    mock_run_course.assert_not_called()


@pytest.mark.asyncio
async def test_write_snapshot_for_day_async_successful_run(
    mock_build_plan_async, mock_run_course, caplog
):
    """
    Test successful execution of write_snapshot_for_day_async with multiple races.
    """
    mock_plan_data = [
        {"course_url": "url1", "date": "2025-01-01", "r_label": "R1", "c_label": "C1"},
        {"course_url": "url2", "date": "2025-01-01", "r_label": "R2", "c_label": "C1"},
    ]
    mock_build_plan_async.return_value = mock_plan_data

    with caplog.at_level(logging.INFO):
        await snapshot_manager.write_snapshot_for_day_async(
            date_str="2025-01-01", phase="H-5", correlation_id="test_id"
        )

    assert "Starting daily snapshot job for 2025-01-01, phase H-5" in caplog.text
    assert "Found 2 races for 2025-01-01. Creating snapshots..." in caplog.text
    assert "Finished creating 2 snapshot tasks for 2025-01-01." in caplog.text

    assert mock_run_course.call_count == 2
    mock_run_course.assert_any_call(
        course_url="url1", phase="H-5", date="2025-01-01", correlation_id="test_id"
    )
    mock_run_course.assert_any_call(
        course_url="url2", phase="H-5", date="2025-01-01", correlation_id="test_id"
    )


@pytest.mark.asyncio
async def test_write_snapshot_for_day_async_incomplete_race_data(
    mock_build_plan_async, mock_run_course, caplog
):
    """
    Test that write_snapshot_for_day_async handles races with incomplete data gracefully.
    """
    mock_plan_data = [
        {"course_url": "url1", "date": "2025-01-01", "r_label": "R1", "c_label": "C1"},
        {"date": "2025-01-01", "r_label": "R2", "c_label": "C1"},  # Missing course_url
        {"course_url": "url3", "r_label": "R3", "c_label": "C1"},  # Missing date
    ]
    mock_build_plan_async.return_value = mock_plan_data

    with caplog.at_level(logging.WARNING):
        await snapshot_manager.write_snapshot_for_day_async(
            date_str="2025-01-01", phase="H-5", correlation_id="test_id"
        )

    assert "Skipping race with incomplete data" in caplog.text
    assert mock_run_course.call_count == 1  # Only the first race should be processed
    mock_run_course.assert_called_once_with(
        course_url="url1", phase="H-5", date="2025-01-01", correlation_id="test_id"
    )


@pytest.mark.asyncio
async def test_write_snapshot_for_day_async_error_handling(
    mock_build_plan_async, mock_run_course, caplog
):
    """
    Test that write_snapshot_for_day_async handles exceptions during plan building.
    """
    mock_build_plan_async.side_effect = Exception("Failed to build plan")

    with caplog.at_level(logging.ERROR):
        await snapshot_manager.write_snapshot_for_day_async(
            date_str="2025-01-01", phase="H-5", correlation_id="test_id"
        )

    assert "Failed during daily snapshot job for 2025-01-01: Failed to build plan" in caplog.text
    mock_run_course.assert_not_called()


def test_write_snapshot_for_day_sync_wrapper(mock_build_plan_async, mock_run_course, monkeypatch):
    """
    Test the synchronous wrapper for write_snapshot_for_day_async.
    """
    mock_asyncio_run = AsyncMock(return_value=None)
    monkeypatch.setattr(snapshot_manager.asyncio, "run", mock_asyncio_run)

    mock_plan_data = [
        {"course_url": "url1", "date": "2025-01-01", "r_label": "R1", "c_label": "C1"},
    ]
    mock_build_plan_async.return_value = mock_plan_data

    snapshot_manager.write_snapshot_for_day(
        date_str="2025-01-01", phase="H-5", correlation_id="test_id"
    )

    mock_asyncio_run.assert_called_once()
    # Verify that asyncio.run was called with the correct coroutine
    assert mock_asyncio_run.call_args[0][0].__name__ == "write_snapshot_for_day_async"

    # Assert that run_course was NOT called, as asyncio.run was mocked and didn't execute the coroutine
    assert mock_run_course.call_count == 0
