import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gcp_exceptions
from pytest_mock import MockerFixture

from hippique_orchestrator import scheduler, time_utils


@pytest.fixture
def mock_tasks_client(mocker: MockerFixture) -> MagicMock:
    """Mocks the CloudTasksClient and its methods."""
    mock_client = MagicMock()
    mock_client.get_task.side_effect = gcp_exceptions.NotFound("Task not found")
    mock_client.task_path.side_effect = (
        lambda project,
        location,
        queue,
        task: f"projects/{project}/locations/{location}/queues/{queue}/tasks/{task}"
    )
    mocker.patch(
        "hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient", return_value=mock_client
    )
    return mock_client


def test_schedule_all_races_creates_h30_and_h5_tasks(mock_tasks_client: MagicMock, mock_config):
    """
    Tests that for a single race in the plan, two tasks (H30 and H5) are created.
    """
    future_date = datetime.now(time_utils.get_tz()) + timedelta(days=1)
    future_time_str = (future_date + timedelta(hours=2)).strftime("%H:%M")
    date_str = future_date.strftime("%Y-%m-%d")

    plan = [
        {
            "date": date_str,
            "r_label": "R1",
            "c_label": "C1",
            "course_url": "http://example.com/r1c1",
            "time_local": future_time_str,
        }
    ]

    results = scheduler.schedule_all_races(
        plan, mode="tasks", correlation_id="test-corr", trace_id="test-trace"
    )

    assert mock_tasks_client.create_task.call_count == 2
    assert len(results) == 2
    assert all(res["ok"] for res in results)

    # Inspect calls to create_task
    h30_call_args = mock_tasks_client.create_task.call_args_list[0]
    h5_call_args = mock_tasks_client.create_task.call_args_list[1]

    h30_task = h30_call_args.kwargs["task"]
    h5_task = h5_call_args.kwargs["task"]

    # Verify H30 task
    h30_payload = json.loads(h30_task["http_request"]["body"])
    assert h30_payload["phase"] == "H30"
    assert h30_payload["course_url"] == "http://example.com/r1c1"

    # Verify H5 task
    h5_payload = json.loads(h5_task["http_request"]["body"])
    assert h5_payload["phase"] == "H5"


def test_enqueue_run_task_skips_past_races(mock_tasks_client: MagicMock, mock_config):
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
