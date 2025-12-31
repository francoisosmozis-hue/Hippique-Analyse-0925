from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
import uuid

from hippique_orchestrator.api.tasks import router
from hippique_orchestrator.service import app

# Mount the tasks router to the main app for testing
app.include_router(router)

client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_dependencies():
    """Mocks external dependencies for api/tasks.py tests."""
    with (
        patch("hippique_orchestrator.api.tasks.write_snapshot_for_day_async", new_callable=AsyncMock) as mock_write_snapshot,
        patch("hippique_orchestrator.service.analysis_pipeline.run_analysis_for_phase", new_callable=AsyncMock) as mock_run_analysis_for_phase,
        patch("hippique_orchestrator.api.tasks.build_plan_async", new_callable=AsyncMock) as mock_build_plan,
        patch("hippique_orchestrator.api.tasks.enqueue_run_task", new_callable=AsyncMock) as mock_enqueue_run_task,
        patch("hippique_orchestrator.api.tasks.config", autospec=True) as mock_config,
        patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"}) as mock_verify_oidc_token,
    ):
        mock_config.h30_offset = timedelta(minutes=30)
        mock_config.h5_offset = timedelta(minutes=5)
        yield {
            "mock_write_snapshot": mock_write_snapshot,
            "mock_run_analysis_for_phase": mock_run_analysis_for_phase,            "mock_build_plan": mock_build_plan,
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
    response = client.post("/tasks/snapshot-9h", json={"date": datetime.now().strftime("%Y-%m-%d")}, headers=headers)
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
async def test_snapshot_9h_task_with_specific_date_and_urls(mock_dependencies, mock_get_correlation_id):
    """
    Test successful H9 snapshot task with a specific date and meeting URLs.
    """
    mock_write_snapshot = mock_dependencies["mock_write_snapshot"]
    test_date = "2025-10-26"
    test_urls = ["http://example.com/r1c1", "http://example.com/r1c2"]
    
    headers = {"Authorization": "Bearer fake-token"}
    response = client.post("/tasks/snapshot-9h", json={"date": test_date, "meeting_urls": test_urls}, headers=headers)
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
    # Mock OIDC token verification for authentication
    mocker.patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"})
    headers = {"Authorization": "Bearer fake-token"}

    test_course_url = "http://example.com/race/2025-12-29_R1C1"
    test_phase = "H30"
    test_date = "2025-12-29"
    test_doc_id = "2025-12-29_R1C1"

    mock_run_analysis_for_phase = mock_dependencies["mock_run_analysis_for_phase"]
    mock_run_analysis_for_phase.return_value = {"success": True, "race_doc_id": test_doc_id, "analysis_result": {"gpi_decision": "PLAY", "status": "success", "tickets_analysis": [], "document_id": test_doc_id}}

    response = client.post(
        "/tasks/run-phase",
        json={"course_url": test_course_url, "phase": test_phase, "date": test_date, "doc_id": test_doc_id},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["analysis"]["status"] == "success"
    assert response.json()["analysis"]["document_id"] == test_doc_id
    assert response.json()["analysis"]["gpi_decision"] == "PLAY"
    
    mock_run_analysis_for_phase.assert_called_once_with(
        course_url=test_course_url,
        phase=test_phase,
        date=test_date,
        correlation_id="12345678-1234-5678-1234-567812345678",
        trace_id=None,
    )

@pytest.mark.asyncio
async def test_run_phase_task_run_course_fails(mock_dependencies, mock_get_correlation_id, mocker):
    """
    Test run-phase task when analysis_pipeline.run_analysis_for_phase returns an error.
    """
    # Mock OIDC token verification for authentication
    mocker.patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"})
    headers = {"Authorization": "Bearer fake-token"}

    mock_run_analysis_for_phase = mock_dependencies["mock_run_analysis_for_phase"]
    # Mock the internal analysis pipeline to simulate a failure
    mock_run_analysis_for_phase.side_effect = Exception("mock_error_from_analysis")

    test_course_url = "http://example.com/race/2025-12-29_R1C1"
    test_phase = "H30"
    test_date = "2025-12-29"
    test_doc_id = "2025-12-29_R1C1"

    response = client.post(
        "/tasks/run-phase",
        json={"course_url": test_course_url, "phase": test_phase, "date": test_date, "doc_id": test_doc_id},
        headers=headers,
    )
    assert response.status_code == 500
    assert "An unexpected exception occurred: mock_error_from_analysis" in response.json()["error"]
    
    mock_run_analysis_for_phase.assert_called_once_with(
        course_url=test_course_url,
        phase=test_phase,
        date=test_date,
        correlation_id="12345678-1234-5678-1234-567812345678",
        trace_id=None,
    )

@pytest.mark.asyncio
async def test_run_phase_task_exception_handling(mock_dependencies, mock_get_correlation_id, mocker):
    """
    Test run-phase task when an unexpected exception occurs.
    """
    # Mock OIDC token verification for authentication
    mocker.patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"})
    headers = {"Authorization": "Bearer fake-token"}

    mock_run_analysis_for_phase = mock_dependencies["mock_run_analysis_for_phase"]
    mock_run_analysis_for_phase.side_effect = Exception("unexpected_error")

    test_course_url = "http://example.com/race/2025-12-29_R1C1"
    test_phase = "H30"
    test_date = "2025-12-29"
    test_doc_id = "2025-12-29_R1C1"

    response = client.post(
        "/tasks/run-phase",
        json={"course_url": test_course_url, "phase": test_phase, "date": test_date, "doc_id": test_doc_id},
        headers=headers,
    )
    assert response.status_code == 500
    assert "An unexpected exception occurred: unexpected_error" in response.json()["error"]

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
            "time_local": (now + timedelta(minutes=10)).strftime("%H:%M"), # H30 would be in the past
            "r_label": "R2",
            "c_label": "C2",
        },
    ]
    mock_build_plan.return_value = mock_plan # Set return value for build_plan_async
    mock_build_plan.return_value = mock_plan # Set return value for build_plan_async
    mocker.patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"})
    headers = {"Authorization": "Bearer fake-token"}
    response = client.post("/tasks/bootstrap-day", json={"date": datetime.now().strftime("%Y-%m-%d")}, headers=headers)
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
    mock_build_plan.return_value = [] # Ensure build_plan_async returns an empty list
    mocker.patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"})
    headers = {"Authorization": "Bearer fake-token"}
    response = client.post("/tasks/bootstrap-day", json={"date": datetime.now().strftime("%Y-%m-%d")}, headers=headers)
    assert response.status_code == 404
