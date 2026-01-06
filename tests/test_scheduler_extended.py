from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import google.auth
from google.api_core import exceptions as gexc
from google.cloud import tasks_v2
from pytest import LogCaptureFixture

from hippique_orchestrator import config, scheduler
from hippique_orchestrator.time_utils import convert_local_to_utc

# A sample plan with one race in the past and one in the future, for today's date
today_str = datetime.now().strftime("%Y-%m-%d")
future_time_str = (datetime.now(timezone.utc) + timedelta(hours=1, minutes=30)).strftime("%H:%M")
past_time_str = (datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)).strftime("%H:%M")

SAMPLE_PLAN_EXTENDED = [
    {
        "r_label": "R1",
        "c_label": "C1",
        "time_local": past_time_str,
        "date": today_str,
        "course_url": "http://example.com/r1c1",
    },
    {
        "r_label": "R1",
        "c_label": "C2",
        "time_local": future_time_str,
        "date": today_str,
        "course_url": "http://example.com/r1c2",
    },
]

# --- Tests for _calculate_task_schedule ---


def test_calculate_task_schedule_invalid_phase_error():
    """
    _calculate_task_schedule should handle an invalid phase string (non-numeric)
    and return a skipped status.
    """
    race_time = "12:00"
    date = "2025-01-01"
    phase = "INVALID"  # Invalid phase
    force = False

    result = scheduler._calculate_task_schedule(race_time, date, phase, force)

    assert result["status"] == "skipped"
    assert result["schedule_time_utc"] is None
    assert "Error calculating schedule time" in result["reason"]


def test_calculate_task_schedule_invalid_race_time_error():
    """
    _calculate_task_schedule should handle an invalid race_time_local string
    and return a skipped status.
    """
    race_time = "not-a-time"  # Invalid time
    date = "2025-01-01"
    phase = "H30"
    force = False

    result = scheduler._calculate_task_schedule(race_time, date, phase, force)

    assert result["status"] == "skipped"
    assert result["schedule_time_utc"] is None
    assert "Error calculating schedule time" in result["reason"]


# --- Tests for enqueue_run_task ---


@patch("hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient")
@patch("hippique_orchestrator.scheduler.google.auth.default")
def test_enqueue_run_task_no_service_url(
    mock_auth_default, mock_cloud_tasks_client, caplog: LogCaptureFixture
):
    """
    enqueue_run_task should return False and an error message if service_url is empty.
    """
    mock_auth_default.return_value = (None, "test-project")
    mock_client_instance = MagicMock()
    mock_cloud_tasks_client.return_value = mock_client_instance

    caplog.set_level("ERROR")

    success, message = scheduler.enqueue_run_task(
        client=mock_client_instance,
        course_url="http://example.com/race",
        phase="H30",
        date="2025-01-01",
        schedule_time_utc=datetime.now(timezone.utc),
        service_url="",  # Empty service URL
    )

    assert not success
    assert "Service URL is not configured" in message
    assert "Service URL is not configured. Cannot create task." in caplog.text
    mock_client_instance.create_task.assert_not_called()


@patch("hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient")
@patch("hippique_orchestrator.scheduler.google.auth.default")
@patch.object(config, "REQUIRE_AUTH", True)
@patch.object(config, "TASK_OIDC_SA_EMAIL", None)
def test_enqueue_run_task_oidc_config_missing(
    mock_auth_default, mock_cloud_tasks_client, caplog: LogCaptureFixture
):
    """
    enqueue_run_task should raise ValueError if REQUIRE_AUTH is True but
    TASK_OIDC_SA_EMAIL is not set.
    """
    mock_auth_default.return_value = (None, "test-project")
    mock_client_instance = MagicMock()
    mock_cloud_tasks_client.return_value = mock_client_instance

    caplog.set_level("ERROR")

    success, message = scheduler.enqueue_run_task(
        client=mock_client_instance,
        course_url="http://example.com/race",
        phase="H30",
        date="2025-01-01",
        schedule_time_utc=datetime.now(timezone.utc),
        service_url="http://test.service",
    )

    assert not success
    assert "TASK_OIDC_SA_EMAIL must be set" in message
    assert "TASK_OIDC_SA_EMAIL must be set when REQUIRE_AUTH is True." in caplog.text
    mock_client_instance.create_task.assert_not_called()


@patch("hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient")
@patch("hippique_orchestrator.scheduler.google.auth.default")
@patch.object(config, "REQUIRE_AUTH", True)
@patch.object(config, "TASK_OIDC_SA_EMAIL", "sa@example.com")
def test_enqueue_run_task_permission_denied(
    mock_auth_default, mock_cloud_tasks_client, caplog: LogCaptureFixture
):
    """
    enqueue_run_task should handle PermissionDenied exception from Cloud Tasks API.
    """
    mock_auth_default.return_value = (None, "test-project")
    mock_client_instance = MagicMock()
    mock_cloud_tasks_client.return_value = mock_client_instance
    mock_client_instance.create_task.side_effect = gexc.PermissionDenied("Forbidden by policy")

    caplog.set_level("CRITICAL")

    success, message = scheduler.enqueue_run_task(
        client=mock_client_instance,
        course_url="http://example.com/race",
        phase="H30",
        date="2025-01-01",
        schedule_time_utc=datetime.now(timezone.utc),
        service_url="http://test.service",
    )

    assert not success
    assert "Permission denied to create Cloud Task" in message
    assert "Please grant 'roles/cloudtasks.enqueuer' to 'sa@example.com'" in caplog.text
    mock_client_instance.create_task.assert_called_once()


@patch("hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient")
@patch("hippique_orchestrator.scheduler.google.auth.default")
def test_enqueue_run_task_generic_exception(
    mock_auth_default, mock_cloud_tasks_client, caplog: LogCaptureFixture
):
    """
    enqueue_run_task should handle generic exceptions from Cloud Tasks API.
    """
    mock_auth_default.return_value = (None, "test-project")
    mock_client_instance = MagicMock()
    mock_cloud_tasks_client.return_value = mock_client_instance
    mock_client_instance.create_task.side_effect = Exception("Network error")

    caplog.set_level("ERROR")

    success, message = scheduler.enqueue_run_task(
        client=mock_client_instance,
        course_url="http://example.com/race",
        phase="H30",
        date="2025-01-01",
        schedule_time_utc=datetime.now(timezone.utc),
        service_url="http://test.service",
    )

    assert not success
    assert "Failed to create task" in message
    assert "Network error" in caplog.text
    mock_client_instance.create_task.assert_called_once()


# --- Tests for schedule_all_races ---


@patch("hippique_orchestrator.scheduler.enqueue_run_task")
@patch("hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient")
def test_schedule_all_races_real_run_no_service_url(
    mock_cloud_tasks_client, mock_enqueue_run_task, caplog: LogCaptureFixture
):
    """
    If service_url is not provided for a real run (dry_run=False),
    schedule_all_races should log a critical error and mark all tasks as failed.
    """
    mock_cloud_tasks_client.return_value = (
        MagicMock()
    )  # Client is initialized but not used for enqueuing
    mock_enqueue_run_task.return_value = (True, "mock-task-name")  # Should not be called

    caplog.set_level("CRITICAL")

    results = scheduler.schedule_all_races(
        plan=SAMPLE_PLAN_EXTENDED, service_url="", force=True, dry_run=False
    )

    assert len(results) == 4  # All 4 potential tasks should be in results
    assert all(not r["ok"] for r in results)
    assert all("Service URL was not provided for a real run." in r["reason"] for r in results)
    assert "Cannot execute real run without a service_url." in caplog.text
    mock_enqueue_run_task.assert_not_called()


@patch("hippique_orchestrator.scheduler.enqueue_run_task")
@patch("hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient")
def test_schedule_all_races_cloud_tasks_client_init_fails(
    mock_cloud_tasks_client, mock_enqueue_run_task, caplog: LogCaptureFixture
):
    """
    If CloudTasksClient initialization fails, schedule_all_races should log
    a critical error and mark all tasks as failed.
    """
    mock_cloud_tasks_client.side_effect = Exception("Client init failed")
    mock_enqueue_run_task.return_value = (True, "mock-task-name")  # Should not be called

    caplog.set_level("CRITICAL")

    results = scheduler.schedule_all_races(
        plan=SAMPLE_PLAN_EXTENDED, service_url="http://test.service", force=True, dry_run=False
    )

    assert len(results) == 4
    assert all(not r["ok"] for r in results)
    assert all(
        "Failed to init CloudTasks client: Client init failed" in r["reason"] for r in results
    )
    assert "Failed to initialize Cloud Tasks client: Client init failed" in caplog.text
    mock_enqueue_run_task.assert_not_called()


@patch("hippique_orchestrator.scheduler.enqueue_run_task")
@patch("hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient")
def test_schedule_all_races_results_are_sorted(mock_cloud_tasks_client, mock_enqueue_run_task):
    """
    schedule_all_races should return results sorted by race and phase.
    """
    mock_client_instance = MagicMock()
    mock_cloud_tasks_client.return_value = mock_client_instance
    mock_client_instance.create_task.return_value = MagicMock(
        name="projects/p/locations/l/queues/q/tasks/t"
    )

    # Make enqueue_run_task return a predictable but out-of-order sequence
    mock_enqueue_run_task.side_effect = [
        (True, "task-R1C2-H30"),
        (True, "task-R1C1-H30"),
        (True, "task-R1C2-H5"),
        (True, "task-R1C1-H5"),
    ]

    # Create a plan that will generate tasks in a specific order for sorting check
    plan_for_sorting = [
        {
            "r_label": "R1",
            "c_label": "C1",
            "time_local": future_time_str,
            "date": today_str,
            "course_url": "http://example.com/r1c1",
        },
        {
            "r_label": "R1",
            "c_label": "C2",
            "time_local": future_time_str,
            "date": today_str,
            "course_url": "http://example.com/r1c2",
        },
    ]

    results = scheduler.schedule_all_races(
        plan=plan_for_sorting, service_url="http://test.service", force=True, dry_run=False
    )

    assert len(results) == 4
    # Expected sorted order: R1C1-H30, R1C1-H5, R1C2-H30, R1C2-H5
    assert results[0]["race"] == "R1C1" and results[0]["phase"] == "H30"
    assert results[1]["race"] == "R1C1" and results[1]["phase"] == "H5"
    assert results[2]["race"] == "R1C2" and results[2]["phase"] == "H30"
    assert results[3]["race"] == "R1C2" and results[3]["phase"] == "H5"
