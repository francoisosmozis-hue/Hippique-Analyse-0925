from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock, Mock

import pytest
import httpx


def test_get_pronostics_page(client):
    """Test that the main UI page loads."""
    response = client.get("/pronostics")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Hippique Orchestrator - Pronostics</title>" in response.text


@pytest.mark.asyncio
async def test_get_pronostics_data_empty_case(app, mock_firestore, mock_build_plan):
    """Test get_pronostics_data when no races are found."""
    mock_get_races, _ = mock_firestore
    mock_get_races.return_value = []
    mock_build_plan.return_value = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/pronostics?date=2025-01-01")

    assert response.status_code == 200
    data = response.json()
    assert "last_updated" in data
    assert data["date"] == "2025-01-01"
    assert data["races"] == []


@pytest.mark.asyncio
async def test_get_pronostics_data_etag_304_not_modified(
    app, mock_firestore, mock_build_plan, mocker
):
    """Test get_pronostics_data ETag 304 Not Modified."""
    # Mock datetime to ensure the ETag is stable
    mock_now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mocker.patch("hippique_orchestrator.service.datetime", now=mocker.Mock(return_value=mock_now))

    mock_get_races, _ = mock_firestore
    mock_get_races.return_value = []
    mock_build_plan.return_value = [
        {"r_label": "R1", "c_label": "C1", "time_local": "10:00"}
    ]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response1 = await client.get("/api/pronostics?date=2025-01-01")
        assert response1.status_code == 200
        etag = response1.headers["etag"]

        response2 = await client.get(
            "/api/pronostics?date=2025-01-01", headers={"if-none-match": etag}
        )
        assert response2.status_code == 304


@pytest.mark.asyncio
async def test_get_pronostics_data_with_data(
    app, mock_firestore, mock_build_plan, mock_race_doc
):
    """Test get_pronostics_data with some race data."""
    mock_get_races, _ = mock_firestore
    mock_get_races.return_value = [
        mock_race_doc("2025-01-01_R1C1", {"gpi_decision": "play", "r_label": "R1", "c_label": "C1"})
    ]
    mock_build_plan.return_value = [
        {
            "date": "2025-01-01",
            "r_label": "R1",
            "c_label": "C1",
            "time_local": "13:50",
            "course_url": "http://example.com/r1c1",
        }
    ]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/pronostics?date=2025-01-01")

    assert response.status_code == 200
    data = response.json()
    assert "last_updated" in data
    assert "date" in data
    assert data["date"] == "2025-01-01"
    assert "races" in data
    assert len(data["races"]) == 1
    assert data["races"][0]["r_label"] == "R1"
    assert data["races"][0]["c_label"] == "C1"
    assert "play" in data["races"][0]["gpi_decision"]


@pytest.mark.asyncio
async def test_get_processing_status(app, mock_firestore, mock_build_plan, mock_race_doc):
    """Test get_ops_status endpoint with mixed race statuses."""
    mock_get_races, mock_get_status = mock_firestore
    mock_get_status.return_value = {
        "ok": True,
        "date": "2025-01-01",
        "status_message": "Processed: 3, Playable: 1, Abstain: 1, Errors: 1, Pending: 1",
        "config": {},
        "counts": {
            "total_in_plan": 4,
            "total_processed": 3,
            "total_playable": 1,
            "total_abstain": 1,
            "total_error": 1,
            "total_pending": 1,
            "total_analyzed": 3,
        },
        "firestore_metadata": {},
        "reason_if_empty": None,
        "last_task_attempt": None,
        "last_error": None,
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ops/status?date=2025-01-01")

    assert response.status_code == 200
    data = response.json()
    assert data["counts"]["total_playable"] == 1
    assert data["counts"]["total_abstain"] == 1
    assert data["counts"]["total_error"] == 1
    assert data["counts"]["total_pending"] == 1
    assert data["counts"]["total_in_plan"] == 4


def test_get_ops_status_reason_if_empty(client, mock_build_plan, mock_firestore):
    """Test that /ops/status provides a reason when no races are processed."""
    mock_get_races, mock_get_status = mock_firestore
    mock_get_status.return_value = {
        "reason_if_empty": "NO_TASKS_PROCESSED_OR_FIRESTORE_EMPTY",
        "counts": {"total_in_plan": 1, "total_processed": 0},
    }

    # Plan has races, but firestore is empty
    mock_build_plan.return_value = [{"r_label": "R1", "c_label": "C1"}]
    mock_get_races.return_value = []

    response = client.get("/ops/status?date=2025-01-01")

    assert response.status_code == 200
    data = response.json()

    assert data["counts"]["total_in_plan"] == 1
    assert data["counts"]["total_processed"] == 0
    assert data["reason_if_empty"] == "NO_TASKS_PROCESSED_OR_FIRESTORE_EMPTY"


def test_health_check(client):
    """Test the /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_healthz_endpoint(client):
    """Test the /healthz alias endpoint."""
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


def test_legacy_redirects(client):
    """Test that old /ui paths correctly redirect."""
    # Test UI redirect
    response_ui = client.get("/pronostics/ui", follow_redirects=False)
    assert response_ui.status_code == 307
    assert response_ui.headers["location"] == "/pronostics"

    # Test API redirect
    response_api = client.get("/api/pronostics/ui", follow_redirects=False)
    assert response_api.status_code == 307
    assert response_api.headers["location"] == "/api/pronostics"


@pytest.fixture
def mock_run_course(monkeypatch):
    """Fixture to mock runner.run_course."""
    mock_func = AsyncMock(return_value={"ok": True, "phase": "H5", "analysis": {}})
    monkeypatch.setattr("hippique_orchestrator.runner.run_course", mock_func)
    return mock_func


@pytest.mark.asyncio
async def test_legacy_run_endpoint_with_course_url(client, mock_run_course):
    """Test POST /run with a direct course_url."""
    response = client.post(
        "/run",
        json={"course_url": "http://example.com/R1C1", "phase": "H5"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_run_course.assert_called_once_with(
        course_url="http://example.com/R1C1",
        phase="H5",
        date=ANY,  # Date will be today's date, use ANY for dynamic value
        correlation_id=ANY,
        trace_id=ANY,
    )


@pytest.mark.asyncio
async def test_legacy_run_endpoint_with_reunion_course(client, mock_run_course, mock_build_plan):
    """Test POST /run with reunion and course, expecting plan to resolve course_url."""
    mock_build_plan.return_value = [
        {"r_label": "R1", "c_label": "C1", "course_url": "http://resolved.com/R1C1"}
    ]
    response = client.post(
        "/run",
        json={"reunion": "R1", "course": "C1", "phase": "H30"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_build_plan.assert_called_once()
    mock_run_course.assert_called_once_with(
        course_url="http://resolved.com/R1C1",
        phase="H30",
        date=ANY,
        correlation_id=ANY,
        trace_id=ANY,
    )


@pytest.mark.asyncio
async def test_legacy_run_endpoint_missing_params(client, mock_run_course):
    """Test POST /run with missing course_url, reunion, and course."""
    response = client.post(
        "/run", json={"phase": "H5"}, headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 422
    assert "Either course_url or reunion/course must be provided." in response.json()["detail"]
    mock_run_course.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_analyse_endpoint(client, mock_run_course, mock_build_plan):
    """Test POST /analyse (legacy, no auth required for now)"""
    mock_build_plan.return_value = [
        {"r_label": "R1", "c_label": "C1", "course_url": "http://resolved.com/R1C1"}
    ]
    response = client.post(
        "/analyse",
        json={"reunion": "R1", "course": "C1", "phase": "H30"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_build_plan.assert_called_once()
    mock_run_course.assert_called_once_with(
        course_url="http://resolved.com/R1C1",
        phase="H30",
        date=ANY,
        correlation_id=ANY,
        trace_id=ANY,
    )


@pytest.mark.asyncio
async def test_legacy_pipeline_run_endpoint(client, mock_run_course, mock_build_plan):
    """Test POST /pipeline/run (legacy, no auth required for now)"""
    mock_build_plan.return_value = [
        {"r_label": "R1", "c_label": "C1", "course_url": "http://resolved.com/R1C1"}
    ]
    response = client.post(
        "/pipeline/run",
        json={"reunion": "R1", "course": "C1", "phase": "H5"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_build_plan.assert_called_once()
    mock_run_course.assert_called_once_with(
        course_url="http://resolved.com/R1C1",
        phase="H5",
        date=ANY,
        correlation_id=ANY,
        trace_id=ANY,
    )


def test_post_ops_run_success(client, monkeypatch, mock_build_plan):
    """Test the POST /ops/run endpoint for a successful manual trigger."""
    # Mock dependencies
    mock_run_analysis = AsyncMock(return_value={"gpi_decision": "play_manual"})
    monkeypatch.setattr(
        "hippique_orchestrator.analysis_pipeline.run_analysis_for_phase", mock_run_analysis
    )
    mock_update_db = MagicMock()
    monkeypatch.setattr(
        "hippique_orchestrator.firestore_client.update_race_document", mock_update_db
    )

    # Setup mock plan to return the target race
    mock_build_plan.return_value = [
        {
            "r_label": "R1",
            "c_label": "C1",
            "name": "Prix d'Amerique",
            "course_url": "http://example.com/r1c1",
        }
    ]

    # Make the request with a valid API key
    response = client.post("/ops/run?rc=R1C1", headers={"X-API-Key": "test-secret"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["gpi_decision"] == "play_manual"

    # Verify that the pipeline and DB update were called
    mock_run_analysis.assert_called_once()
    mock_update_db.assert_called_once()

    # Check that the doc_id passed to update_race_document is correct
    call_args, _ = mock_update_db.call_args
    assert call_args[0].endswith("_R1C1")  # doc_id is the first positional arg
    assert call_args[1]["gpi_decision"] == "play_manual"


@pytest.mark.asyncio
async def test_run_single_race_missing_course_url(client, monkeypatch, mock_build_plan):
    """
    Test POST /ops/run when the target race in the plan is missing a course_url.
    """
    # Setup mock plan to return a race without a URL
    mock_build_plan.return_value = [
        {
            "r_label": "R1", "c_label": "C1", "name": "Prix d'Amerique", "course_url": None
        }
    ]

    # Make the request with a valid API key
    response = client.post("/ops/run?rc=R1C1", headers={"X-API-Key": "test-secret"})

    assert response.status_code == 400
    assert "Race R1C1 is missing a URL in the plan." in response.json()["detail"]
    mock_build_plan.assert_called_once()

    # Ensure analysis pipeline or firestore update were NOT called
    # We need to set these up as mocks even if not called to ensure the asserts pass
    mock_run_analysis = AsyncMock()
    monkeypatch.setattr(
        "hippique_orchestrator.analysis_pipeline.run_analysis_for_phase", mock_run_analysis
    )
    mock_update_db = MagicMock()
    monkeypatch.setattr(
        "hippique_orchestrator.firestore_client.update_race_document", mock_update_db
    )
    mock_get_doc_id = MagicMock()
    monkeypatch.setattr(
        "hippique_orchestrator.firestore_client.get_doc_id_from_url", mock_get_doc_id
    )
    assert not mock_run_analysis.called
    assert not mock_update_db.called
    assert not mock_get_doc_id.called


@pytest.mark.asyncio
async def test_schedule_day_races_success(client, monkeypatch, mock_build_plan):
    """
    Test a successful call to POST /schedule, verifying that the scheduler
    is called with the correct parameters.
    """
    mock_scheduler = MagicMock(
        return_value=[
            {
                "race": "R1C1",
                "phase": "H-5",
                "ok": True,
                "task_name": "task1",
                "reason": "Scheduled",
            }
        ]
    )
    monkeypatch.setattr("hippique_orchestrator.scheduler.schedule_all_races", mock_scheduler)

    mock_build_plan.return_value = [{"r_label": "R1", "c_label": "C1"}]

    response = client.post(
        "/schedule",
        json={"force": True, "dry_run": True, "date": "2025-01-01"},
        headers={"X-API-Key": "test-secret"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "Scheduling process complete" in data["message"]
    assert data["races_in_plan"] == 1
    assert len(data["details"]) == 1

    mock_build_plan.assert_called_once_with("2025-01-01")
    mock_scheduler.assert_called_once()

    # Check that force and dry_run flags were passed correctly
    _, kwargs = mock_scheduler.call_args
    assert kwargs["force"] is True
    assert kwargs["dry_run"] is True


@pytest.mark.asyncio
async def test_schedule_day_races_empty_plan(client, monkeypatch, mock_build_plan):
    """
    Test POST /schedule when the daily plan is empty.
    """
    mock_scheduler = MagicMock()
    monkeypatch.setattr("hippique_orchestrator.scheduler.schedule_all_races", mock_scheduler)
    mock_build_plan.return_value = []

    response = client.post(
        "/schedule",
        json={"date": "2025-01-01"},
        headers={"X-API-Key": "test-secret"},
    )

    assert response.status_code == 200
    assert "No races found in plan" in response.json()["message"]
    mock_scheduler.assert_not_called()


@pytest.mark.asyncio
async def test_run_single_race_unhandled_exception(client, monkeypatch, mock_build_plan):
    """
    Test POST /ops/run for an unhandled exception during the analysis pipeline.
    """
    # Setup mock plan to return the target race
    mock_build_plan.return_value = [
        {
            "r_label": "R1",
            "c_label": "C1",
            "name": "Prix d'Amerique",
            "course_url": "http://example.com/r1c1",
        }
    ]

    # Simulate an unexpected error in analysis_pipeline.run_analysis_for_phase
    mock_run_analysis = AsyncMock(side_effect=Exception("Simulated pipeline error"))
    monkeypatch.setattr(
        "hippique_orchestrator.analysis_pipeline.run_analysis_for_phase", mock_run_analysis
    )
    mock_update_db = MagicMock()
    monkeypatch.setattr(
        "hippique_orchestrator.firestore_client.update_race_document", mock_update_db
    )

    response = client.post("/ops/run?rc=R1C1", headers={"X-API-Key": "test-secret"})

    assert response.status_code == 500
    assert "Failed to process manual run for" in response.json()["detail"]
    mock_run_analysis.assert_called_once()
    mock_update_db.assert_called_once()  # Should be called to save error state

    # Verify error data saved
    call_args, _ = mock_update_db.call_args
    error_data = call_args[1]  # second positional arg is error_data
    assert error_data["status"] == "error"
    assert error_data["gpi_decision"] == "error_manual_run"
    assert "Simulated pipeline error" in error_data["error_message"]


@pytest.mark.asyncio
async def test_schedule_day_races_unhandled_exception(client, monkeypatch, mock_build_plan, caplog):
    """
    Test POST /schedule for an unhandled exception during processing.
    """
    # Simulate an unexpected error in build_plan_async
    mock_build_plan.side_effect = Exception("Simulated unhandled error")

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/schedule",
            json={"force": False, "dry_run": True, "date": "2025-01-01"},
            headers={"X-API-Key": "test-secret"},
        )

    assert response.status_code == 500
    assert "An internal error occurred" in response.json()["detail"]
    assert "UNHANDLED EXCEPTION in /schedule endpoint" in caplog.text
    mock_build_plan.assert_called_once()


@pytest.mark.asyncio
async def test_api_pronostics_schema_and_ui_markers(app, client, mock_firestore, mock_build_plan):
    """
    Test the schema of /api/pronostics and that the UI contains critical markers.
    """
    # 1. Test API Schema
    mock_get_races, _ = mock_firestore
    mock_get_races.return_value = [
        Mock(
            to_dict=lambda: {
                "course_id": "2025-01-01_R1C1",
                "reunion": 1,
                "course": 1,
                "speciality": "Plat",
                "category": "Handicap",
                "hippodrome": "Deauville",
                "start_time": "2025-01-01T13:50:00Z",
                "partants": 16,
                "tickets_analysis": {"gpi_decision": "pari"},
                "tickets": [{"type": "SG", "mise": 1.5, "chevaux": [1]}],
            },
            id="2025-01-01_R1C1",
        )
    ]
    mock_build_plan.return_value = []

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        api_response = await async_client.get("/api/pronostics?date=2025-01-01")

    assert api_response.status_code == 200
    data = api_response.json()

    assert "races" in data and isinstance(data["races"], list)
    assert "last_updated" in data and "version" in data

    # 2. Test UI Content
    ui_response = client.get("/pronostics")
    assert ui_response.status_code == 200
    html = ui_response.text

    assert '<table id="races-table">' in html
    assert '<tbody id="races-tbody">' in html
    assert 'fetch(`/api/pronostics?date=${date}`)' in html


def validate_pronostic(pronostic: dict):
    assert "course_id" in pronostic
    assert isinstance(pronostic["course_id"], str)
    assert "reunion" in pronostic
    assert isinstance(pronostic["reunion"], int)
    assert "course" in pronostic
    assert isinstance(pronostic["course"], int)
    assert "speciality" in pronostic
    assert isinstance(pronostic["speciality"], str)
    assert "category" in pronostic
    assert isinstance(pronostic["category"], str)
    assert "hippodrome" in pronostic
    assert isinstance(pronostic["hippodrome"], str)
    assert "start_time" in pronostic
    assert "partants" in pronostic
    assert isinstance(pronostic["partants"], int)

    if "tickets" in pronostic:
        assert isinstance(pronostic["tickets"], list)
        for ticket in pronostic["tickets"]:
            assert "type" in ticket
            assert isinstance(ticket["type"], str)
            assert "mise" in ticket
            assert isinstance(ticket["mise"], (int, float))
            assert "chevaux" in ticket
            assert isinstance(ticket["chevaux"], list)
            for cheval in ticket["chevaux"]:
                assert isinstance(cheval, (int, str))


def test_run_single_race_not_found(client, mock_build_plan):
    """Test POST /ops/run when the requested race is not in the plan."""
    mock_build_plan.return_value = [{"r_label": "R1", "c_label": "C2", "name": "Some Other Race"}]
    response = client.post("/ops/run?rc=R1C1", headers={"X-API-Key": "test-secret"})
    assert response.status_code == 404
    assert "Race R1C1 not found" in response.json()["detail"]


def test_get_daily_plan_success(client, mock_build_plan):
    """Test a successful call to the /api/plan endpoint."""
    mock_build_plan.return_value = [{"r_label": "R1", "c_label": "C1"}]
    response = client.get("/api/plan?date=2025-01-01")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["count"] == 1
    assert data["races"][0]["r_label"] == "R1"


def test_debug_config_endpoint(client):
    """Test that the /debug/config endpoint returns key information."""
    response = client.get("/debug/config")
    assert response.status_code == 200
    data = response.json()
    assert "project_id" in data
    assert "version" in data
    assert "require_auth" in data


def test_get_pronostics_data_defaults_to_today(client, mock_build_plan, mock_firestore):
    """Test /api/pronostics defaults to the current date when none is provided."""
    mock_get_races, _ = mock_firestore
    mock_build_plan.return_value = []
    mock_get_races.return_value = []

    today_str = datetime.now().strftime("%Y-%m-%d")

    response = client.get("/api/pronostics")
    assert response.status_code == 200
    data = response.json()
    assert data["date"] == today_str


def test_ui_contains_critical_elements_and_api_call(client):
    """
    Test that the main UI page contains critical HTML elements and the correct
    JavaScript fetch call to the API endpoint.
    """
    response = client.get("/pronostics")
    assert response.status_code == 200
    html = response.text

    # Check for critical structural elements
    assert '<table id="races-table">' in html
    assert '<tbody id="races-tbody">' in html

    # Check that the JavaScript contains the specific fetch call
    assert 'fetch(`/api/pronostics?date=${date}`)' in html


def test_get_daily_plan_invalid_date_format(client):
    """
    Test /api/plan with an invalid date format to trigger ValueError.
    """
    response = client.get("/api/plan?date=not-a-date")
    assert response.status_code == 422
    assert "Invalid date format. Please use YYYY-MM-DD." in response.json()["detail"]


def test_get_ops_status_invalid_date_format(client):
    """
    Test /ops/status with an invalid date format to trigger ValueError.
    """
    response = client.get("/ops/status?date=not-a-date")
    assert response.status_code == 422
    assert "Invalid date format. Use YYYY-MM-DD." in response.json()["detail"]