import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_app import create_app
from hippique_orchestrator.data_contract import Programme
from hippique_orchestrator.schemas import BootstrapDayRequest
from hippique_orchestrator.config import PROJECT_ID, TASK_QUEUE, TASK_OIDC_SA_EMAIL

@pytest.fixture(name="app")
def fixture_app() -> FastAPI:
    return create_app()

@pytest.fixture(name="client")
def fixture_client(app: FastAPI) -> TestClient:
    return TestClient(app)

# This is a temporary patch for Programme.model_validate. The mock for this
# needs to provide valid data for the Race.hippodrome, because the Race model
# has been updated to make hippodrome optional, but the current test data
# structure doesn't reflect this.
# TODO: Refactor test data / mocks to properly handle the optional hippodrome field.
class PatchedProgramme(Programme):
    @classmethod
    def model_validate(cls, data):
        # Ensure that if hippodrome is missing, it's set to None explicitly
        for race in data.get("races", []):
            if "hippodrome" not in race:
                race["hippodrome"] = None
        return Programme.model_validate(data)

@pytest.fixture(autouse=True)
def patch_programme_model_validate(mocker):
    original_model_validate = Programme.model_validate
    def mocked_model_validate(data):
        # Ensure that if hippodrome is missing, it's set to None explicitly
        for race in data.get("races", []):
            if "hippodrome" not in race:
                race["hippodrome"] = None
        return original_model_validate(data)

    mocker.patch('hippique_orchestrator.data_contract.Programme.model_validate', side_effect=mocked_model_validate)

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
            "starlette.concurrency.run_in_threadpool",
            new_callable=AsyncMock,
        ) as mock_run_in_threadpool,
        patch(
            "hippique_orchestrator.scheduler.schedule_all_races",
            return_value=[
                {"ok": True, "race": "race1", "phase": "H30", "task_name": "task1", "reason": None},
                {"ok": True, "race": "race1", "phase": "H5", "task_name": "task2", "reason": None},
                {"ok": True, "race": "race2", "phase": "H5", "task_name": "task3", "reason": None}
            ]
        ) as mock_schedule_all_races,
        patch(
            "google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"}
        ) as mock_verify_oidc_token,
        patch("hippique_orchestrator.api.tasks.firestore_client.update_race_document", AsyncMock()) as mock_update_race_document,
        patch("hippique_orchestrator.api.tasks.firestore_client.get_doc_id_from_url", return_value="2025-12-29_R1C1") as mock_get_doc_id_from_url,
    ):
        yield {
            "mock_write_snapshot": mock_write_snapshot,
            "mock_run_course": mock_run_course,
            "mock_build_plan": mock_build_plan,
            "mock_run_in_threadpool": mock_run_in_threadpool,
            "mock_schedule_all_races": mock_schedule_all_races,
            "mock_verify_oidc_token": mock_verify_oidc_token,
            "mock_update_race_document": mock_update_race_document,
            "mock_get_doc_id_from_url": mock_get_doc_id_from_url,
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
async def test_snapshot_9h_task_success(client: TestClient, mock_dependencies, mocker, oidc_token_header):
    """
    Test successful H9 snapshot task with default date.
    """
    mocker.patch("hippique_orchestrator.logging_utils.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"))
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
    client: TestClient, mock_dependencies, mocker, oidc_token_header
):
    mocker.patch("hippique_orchestrator.logging_utils.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"))
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
async def test_run_phase_task_success(client: TestClient, mock_dependencies, mocker, oidc_token_header):
    """
    Test successful run-phase task.
    """
    mocker.patch("hippique_orchestrator.logging_utils.uuid.uuid4", return_value=uuid.UUID("12345678-1234-5678-1234-567812345678"))
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
    client: TestClient, mock_dependencies, mocker, oidc_token_header
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
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["ok"] is False
    assert response_data["error"] == "Runner failed"


@pytest.mark.asyncio
async def test_run_phase_task_exception_handling(
    client: TestClient, mock_dependencies, mocker, oidc_token_header
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
async def test_snapshot_9h_task_exception(client: TestClient, mock_dependencies, oidc_token_header):
    """Test exception handling in the snapshot-9h task."""
    mock_dependencies["mock_write_snapshot"].side_effect = Exception("Storage error")

    headers = {"Authorization": "Bearer fake-token"}
    response = client.post("/tasks/snapshot-9h", json={"date": "2025-10-26"}, headers=headers)

    assert response.status_code == 500
    assert "Internal server error during snapshot-9h: Storage error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_bootstrap_day_task_exception(client: TestClient, mock_dependencies, oidc_token_header):
    """Test exception handling in the bootstrap-day task."""
    mock_dependencies["mock_build_plan"].side_effect = Exception("Plan build failed")

    headers = {"Authorization": "Bearer fake-token"}
    response = client.post("/tasks/bootstrap-day", json={"date": "2025-10-26"}, headers=headers)

    assert response.status_code == 500
    assert "Internal server error during bootstrap: Plan build failed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_run_phase_task_infers_doc_id(client: TestClient, mock_dependencies, mocker, oidc_token_header):
    """Test that run-phase task correctly infers doc_id if not provided."""
    headers = {"Authorization": "Bearer fake-token"}
    mock_run_course = mock_dependencies["mock_run_course"]
    mock_run_course.return_value = {"ok": True}

    mock_update = mock_dependencies["mock_update_race_document"]
    mock_get_doc_id = mock_dependencies["mock_get_doc_id_from_url"]

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
    mock_get_doc_id.assert_called_once_with("http://example.com/2025-01-01/R1C1-race", "2025-01-01")
    mock_update.assert_called_once_with(
        "2025-12-29_R1C1", {"ok": True, "last_analyzed_at": mocker.ANY}
    )


# ============================================
# /tasks/bootstrap-day Tests
# ============================================


@pytest.mark.asyncio
async def test_bootstrap_day_task_success(client: TestClient, mock_dependencies, oidc_token_header):
    """
    Test successful bootstrap-day task where tasks are scheduled.
    """
    mock_build_plan = mock_dependencies["mock_build_plan"]
    mock_schedule_all_races = mock_dependencies["mock_schedule_all_races"]

    now = datetime.now()
    mock_plan = [
        {
            "course_url": "http://example.com/race1",
            "time_local": (now + timedelta(hours=1)).strftime("%H:%M"),
            "r_label": "R1",
            "c_label": "C1",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
        {
            "course_url": "http://example.com/race2",
            "time_local": (now + timedelta(minutes=10)).strftime("%H:%M"),
            "r_label": "R2",
            "c_label": "C2",
            "date": datetime.now().strftime("%Y-%m-%d"),
        },
    ]
    mock_build_plan.return_value = mock_plan

    headers = {"Authorization": "Bearer fake-token"}
    response = client.post(
        "/tasks/bootstrap-day", json={"date": datetime.now().strftime("%Y-%m-%d")}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "done" in response.json()["message"]
    assert response.json()["date"] == datetime.now().strftime("%Y-%m-%d")
    assert response.json()["details"] == mock_schedule_all_races.return_value

    mock_schedule_all_races.assert_called_once_with(
        mock_plan,
        "http://testserver",
        False,  # force
        False,  # dry_run
    )


@pytest.mark.asyncio
async def test_bootstrap_day_task_empty_plan(client: TestClient, mock_dependencies, oidc_token_header):
    """
    Test bootstrap-day task when build_plan_async returns an empty plan.
    """
    mock_build_plan = mock_dependencies["mock_build_plan"]
    mock_run_in_threadpool = mock_dependencies["mock_run_in_threadpool"]

    mock_build_plan.return_value = []  # Ensure build_plan_async returns an empty list
    mock_run_in_threadpool.return_value = [] # run_in_threadpool will be called with an empty plan, returning empty results.

    headers = {"Authorization": "Bearer fake-token"}
    response = client.post(
        "/tasks/bootstrap-day", json={"date": datetime.now().strftime("%Y-%m-%d")}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "No races found for scheduling" in response.json()["message"]

    mock_build_plan.assert_called_once()
    mock_run_in_threadpool.assert_not_called()
