import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from hippique_orchestrator.api.tasks import router
from hippique_orchestrator.service import app

# Mount the tasks router to the main app for testing
app.include_router(router)

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mocks external dependencies for api/tasks.py tests."""
    with (
        patch(
            "hippique_orchestrator.api.tasks.write_snapshot_for_day_async", new_callable=AsyncMock
        ) as mock_write_snapshot,
        patch(
            "hippique_orchestrator.api.tasks.run_course", new_callable=AsyncMock
        ) as mock_run_course,
        patch(
            "hippique_orchestrator.api.tasks.build_plan_async", new_callable=AsyncMock
        ) as mock_build_plan,
        patch(
            "hippique_orchestrator.api.tasks.enqueue_run_task", new_callable=AsyncMock
        ) as mock_enqueue_run_task,
        patch("hippique_orchestrator.api.tasks.config", autospec=True) as mock_config,
        patch(
            "google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"}
        ) as mock_verify_oidc_token,
    ):
        mock_config.h30_offset = timedelta(minutes=30)
        mock_config.h5_offset = timedelta(minutes=5)
        yield {
            "mock_write_snapshot": mock_write_snapshot,
            "mock_run_course": mock_run_course,
            "mock_build_plan": mock_build_plan,
            "mock_enqueue_run_task": mock_enqueue_run_task,
            "mock_config": mock_config,
            "mock_verify_oidc_token": mock_verify_oidc_token,
        }


@pytest.fixture
def mock_get_correlation_id(mocker):
    """Mocks the correlation_id generation for consistent testing."""
    mock_uuid4 = mocker.patch("uuid.uuid4")
    mock_uuid4.return_value = uuid.UUID("12345678-1234-5678-1234-567812345678")
    yield


# ============================================
# /tasks/snapshot-9h Tests
# ============================================


@pytest.mark.asyncio
async def test_snapshot_9h_task_success(mock_dependencies, mock_get_correlation_id):
    """
    Test successful H9 snapshot task with default date.
    """
    mock_write_snapshot = mock_dependencies["mock_write_snapshot"]

    headers = {"Authorization": "Bearer fake-token"}
    response = client.post(
        "/tasks/snapshot-9h", json={"date": datetime.now().strftime("%Y-%m-%d")}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "initiated" in response.json()["message"]

    current_date = datetime.now().strftime("%Y-%m-%d")
    mock_write_snapshot.assert_called_once_with(
        date_str=current_date,
        race_urls=[],
        rc_labels=[],
        phase="H9",
        correlation_id="12345678-1234-5678-1234-567812345678",
    )


@pytest.mark.asyncio
async def test_snapshot_9h_task_with_specific_date_and_urls(
    mock_dependencies, mock_get_correlation_id
):
    """
    Test successful H9 snapshot task with a specific date and meeting URLs.
    """
    mock_write_snapshot = mock_dependencies["mock_write_snapshot"]
    test_date = "2025-10-26"
    test_urls = ["http://example.com/r1c1", "http://example.com/r1c2"]

    headers = {"Authorization": "Bearer fake-token"}
    response = client.post(
        "/tasks/snapshot-9h", json={"date": test_date, "meeting_urls": test_urls}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["date"] == test_date

    mock_write_snapshot.assert_called_once_with(
        date_str=test_date,
        race_urls=test_urls,
        rc_labels=[],
        phase="H9",
        correlation_id="12345678-1234-5678-1234-567812345678",
    )


# ============================================
# /tasks/run-phase Tests
# ============================================


@pytest.mark.asyncio
async def test_run_phase_task_success(mock_dependencies, mock_get_correlation_id, mocker):
    """
    Test successful run-phase task.
    """
    headers = {"Authorization": "Bearer fake-token"}

    test_course_url = "http://example.com/race/2025-12-29/R1C1-prix-de-la-course"
    test_phase = "H30"
    test_date = "2025-12-29"
    test_doc_id = "2025-12-29_R1C1"

    mock_run_course = mock_dependencies["mock_run_course"]
    mock_run_course.return_value = {"ok": True, "gpi_decision": "PLAY", "status": "success"}

    mock_update_doc = mocker.patch(
        "hippique_orchestrator.api.tasks.firestore_client.update_race_document"
    )

    response = client.post(
        "/tasks/run-phase",
        json={"course_url": test_course_url, "phase": test_phase, "date": test_date},
        headers=headers,
    )

    assert response.status_code == 200
    response_data = response.json()
    assert response_data["status"] == "success"
    assert response_data["gpi_decision"] == "PLAY"

    mock_run_course.assert_called_once_with(
        course_url=test_course_url,
        phase=test_phase,
        date=test_date,
        correlation_id="12345678-1234-5678-1234-567812345678",
    )
    mock_update_doc.assert_called_once()
    assert mock_update_doc.call_args[0][0] == test_doc_id


@pytest.mark.asyncio
async def test_run_phase_task_runner_returns_error(
    mock_dependencies, mock_get_correlation_id, mocker
):
    """
    Test run-phase when the runner returns a non-OK status.
    """
    headers = {"Authorization": "Bearer fake-token"}
    mock_run_course = mock_dependencies["mock_run_course"]
    error_payload = {"ok": False, "error": "Runner failed"}
    mock_run_course.return_value = error_payload

    response = client.post(
        "/tasks/run-phase",
        json={"course_url": "http://example.com/R1C1", "phase": "H5", "date": "date"},
        headers=headers,
    )
    assert response.status_code == 500
    # The endpoint adds the correlation_id to the response
    expected_response = {**error_payload, "correlation_id": "12345678-1234-5678-1234-567812345678"}
    assert response.json() == expected_response


@pytest.mark.asyncio
async def test_run_phase_task_exception_handling(
    mock_dependencies, mock_get_correlation_id, mocker
):
    """
    Test run-phase task when an unexpected exception occurs.
    """
    headers = {"Authorization": "Bearer fake-token"}
    mock_run_course = mock_dependencies["mock_run_course"]
    mock_run_course.side_effect = Exception("unexpected_error")

    mock_update_db = mocker.patch(
        "hippique_orchestrator.api.tasks.firestore_client.update_race_document"
    )

    response = client.post(
        "/tasks/run-phase",
        json={"course_url": "http://example.com/R1C1", "phase": "H5", "date": "date"},
        headers=headers,
    )
    assert response.status_code == 500
    assert "Internal server error: unexpected_error" in response.json()["detail"]
    mock_update_db.assert_not_called()


@pytest.mark.asyncio
async def test_snapshot_9h_task_exception(mock_dependencies, mock_get_correlation_id):
    """Test exception handling in the snapshot-9h task."""
    mock_dependencies["mock_write_snapshot"].side_effect = Exception("Storage error")

    headers = {"Authorization": "Bearer fake-token"}
    response = client.post("/tasks/snapshot-9h", json={"date": "2025-10-26"}, headers=headers)

    assert response.status_code == 500
    assert "Internal server error during snapshot-9h: Storage error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_bootstrap_day_task_exception(mock_dependencies, mock_get_correlation_id):
    """Test exception handling in the bootstrap-day task."""
    mock_dependencies["mock_build_plan"].side_effect = Exception("Plan build failed")

    headers = {"Authorization": "Bearer fake-token"}
    response = client.post("/tasks/bootstrap-day", json={"date": "2025-10-26"}, headers=headers)

    assert response.status_code == 500
    assert "Internal server error during bootstrap: Plan build failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_run_phase_task_infers_doc_id(mock_dependencies, mock_get_correlation_id, mocker):
    """Test that run-phase task correctly infers doc_id if not provided."""
    headers = {"Authorization": "Bearer fake-token"}
    mock_run_course = mock_dependencies["mock_run_course"]
    mock_run_course.return_value = {"ok": True}

    # This mock is now inside the correct test
    mock_update = mocker.patch(
        "hippique_orchestrator.api.tasks.firestore_client.update_race_document"
    )

    response = client.post(
        "/tasks/run-phase",
        json={
            "course_url": "http://example.com/2025-01-01/R1C1-race",
            "phase": "H5",
            "date": "2025-01-01",
        },  # No doc_id
        headers=headers,
    )

    assert response.status_code == 200
    mock_update.assert_called_once()
    assert mock_update.call_args[0][0] == "2025-01-01_R1C1"


# ============================================
# /tasks/bootstrap-day Tests
# ============================================


@pytest.mark.asyncio
async def test_bootstrap_day_task_success(mock_dependencies, mock_get_correlation_id, mocker):
    """
    Test successful bootstrap-day task where tasks are scheduled.
    """
    mock_build_plan = mock_dependencies["mock_build_plan"]
    mock_enqueue_run_task = mock_dependencies["mock_enqueue_run_task"]

    # Mock a plan with two races, one of which schedules both H30 and H5,
    # and another that schedules only H5 because H30 is in the past.
    now = datetime.now()
    mock_plan = [
        {
            "course_url": "http://example.com/race1",
            "time_local": (now + timedelta(hours=1)).strftime("%H:%M"),
            "r_label": "R1",
            "c_label": "C1",
        },
        {
            "course_url": "http://example.com/race2",
            "time_local": (now + timedelta(minutes=10)).strftime(
                "%H:%M"
            ),  # H30 would be in the past
            "r_label": "R2",
            "c_label": "C2",
        },
    ]
    mock_build_plan.return_value = mock_plan  # Set return value for build_plan_async
    mock_build_plan.return_value = mock_plan  # Set return value for build_plan_async
    mocker.patch(
        "google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"}
    )
    headers = {"Authorization": "Bearer fake-token"}
    response = client.post(
        "/tasks/bootstrap-day", json={"date": datetime.now().strftime("%Y-%m-%d")}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "initiated" in response.json()["message"]
    assert response.json()["total_races"] == 2

    # Assert calls to enqueue_run_task
    # Race 1: Both H30 and H5 should be scheduled
    mock_enqueue_run_task.assert_any_call(
        course_url="http://example.com/race1",
        phase="H30",
        date=datetime.now().strftime("%Y-%m-%d"),
        race_time_local=mock_plan[0]["time_local"],
        r_label="R1",
        c_label="C1",
        correlation_id="12345678-1234-5678-1234-567812345678",
    )
    mock_enqueue_run_task.assert_any_call(
        course_url="http://example.com/race1",
        phase="H5",
        date=datetime.now().strftime("%Y-%m-%d"),
        race_time_local=mock_plan[0]["time_local"],
        r_label="R1",
        c_label="C1",
        correlation_id="12345678-1234-5678-1234-567812345678",
    )
    # Race 2: Only H5 should be scheduled (H30 in past)
    mock_enqueue_run_task.assert_any_call(
        course_url="http://example.com/race2",
        phase="H5",
        date=datetime.now().strftime("%Y-%m-%d"),
        race_time_local=mock_plan[1]["time_local"],
        r_label="R2",
        c_label="C2",
        correlation_id="12345678-1234-5678-1234-567812345678",
    )

    # 3 tasks should have been scheduled (H30 for race1, H5 for race1, H5 for race2)
    assert mock_enqueue_run_task.call_count == 3
    assert response.json()["scheduled_tasks"] == 3


@pytest.mark.asyncio
async def test_bootstrap_day_task_empty_plan(mock_dependencies, mock_get_correlation_id, mocker):
    """
    Test bootstrap-day task when build_plan_async returns an empty plan.
    """
    mock_build_plan = mock_dependencies["mock_build_plan"]
    mock_build_plan.return_value = []  # Ensure build_plan_async returns an empty list
    mocker.patch(
        "google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"}
    )
    headers = {"Authorization": "Bearer fake-token"}
    response = client.post(
        "/tasks/bootstrap-day", json={"date": datetime.now().strftime("%Y-%m-%d")}, headers=headers
    )
    assert response.status_code == 404
