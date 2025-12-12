import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gcp_exceptions
from pytest_mock import MockerFixture

from hippique_orchestrator import scheduler


@pytest.fixture
def mock_tasks_client(mocker: MockerFixture) -> MagicMock:
    """Mocks the CloudTasksClient and its methods."""
    mock_client = MagicMock()
    # Simulate that tasks do not exist by default, so create_task should be called
    mock_client.get_task.side_effect = gcp_exceptions.NotFound("Task not found")
    
    # Patch the client inside the scheduler module
    mocker.patch("hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient", return_value=mock_client)
    
    return mock_client


def test_schedule_all_races_creates_h30_and_h5_tasks(mock_tasks_client: MagicMock):
    """
    Tests that for a single race in the plan, two tasks (H30 and H5) are created.
    """
    # Define a race time in the future to ensure tasks are schedulable
    tomorrow = datetime.now() + timedelta(days=1)
    future_time = (datetime.now() + timedelta(hours=2)).strftime("%H:%M")
    
    plan = [
        {
            "date": tomorrow.strftime("%Y-%m-%d"),
            "r_label": "R1",
            "c_label": "C1",
            "course_url": "http://example.com/r1c1",
            "time_local": future_time,
        }
    ]

    # Act
    results = scheduler.schedule_all_races(plan, mode="tasks", correlation_id="test-corr", trace_id="test-trace")

    # Assert
    assert mock_tasks_client.create_task.call_count == 2
    assert len(results) == 2
    assert all(res["ok"] for res in results)

    # Inspect the H30 task
    h30_call_args = mock_tasks_client.create_task.call_args_list[0]
    h30_task_payload = json.loads(h30_call_args.kwargs["task"]["http_request"]["body"])
    assert h30_task_payload["phase"] == "H30"
    assert "h30" in h30_call_args.kwargs["task"]["name"]

    # Inspect the H5 task
    h5_call_args = mock_tasks_client.create_task.call_args_list[1]
    h5_task_payload = json.loads(h5_call_args.kwargs["task"]["http_request"]["body"])
    assert h5_task_payload["phase"] == "H5"
    assert "h5" in h5_call_args.kwargs["task"]["name"]


def test_schedule_all_races_skips_existing_tasks(mock_tasks_client: MagicMock):
    """
    Tests idempotency: if get_task succeeds (doesn't raise NotFound),
    then create_task should not be called.
    """
    # Override the default mock behavior to simulate tasks already existing
    mock_tasks_client.get_task.side_effect = None  # get_task now returns the default MagicMock, not an error
    mock_tasks_client.get_task.return_value = MagicMock() # Be explicit

    future_time = (datetime.now() + timedelta(hours=2)).strftime("%H:%M")
    plan = [
        {
            "date": "2025-12-25",
            "r_label": "R1",
            "c_label": "C1",
            "course_url": "http://example.com/r1c1",
            "time_local": future_time,
        }
    ]

    # Act
    scheduler.schedule_all_races(plan, mode="tasks", correlation_id="test-corr", trace_id="test-trace")

    # Assert
    # get_task should have been called twice (for H30 and H5)
    assert mock_tasks_client.get_task.call_count == 2
    # create_task should never be called because the tasks "exist"
    assert mock_tasks_client.create_task.call_count == 0


def test_enqueue_run_task_skips_past_races(mock_tasks_client: MagicMock):
    """
    Tests that no task is created if the calculated snapshot time is in the past.
    """
    past_time = (datetime.now() - timedelta(hours=1)).strftime("%H:%M")
    today = datetime.now().strftime("%Y-%m-%d")
    
    res = scheduler.enqueue_run_task(
        client=mock_tasks_client,
        course_url="http://example.com/r1c1",
        phase="H30",
        date=today,
        race_time_local=past_time,
        r_label="R1",
        c_label="C1",
    )

    assert res is None
    assert mock_tasks_client.create_task.call_count == 0
