from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

# Mock the firestore client before it's imported by the service
from hippique_orchestrator import firestore_client

firestore_client.db = MagicMock()


@pytest.fixture
def mock_plan(monkeypatch):
    """Fixture to mock plan.build_plan_async."""
    mock_build_plan = AsyncMock()
    monkeypatch.setattr("hippique_orchestrator.plan.build_plan_async", mock_build_plan)
    return mock_build_plan


@pytest.fixture
def mock_firestore(monkeypatch):
    """Fixture to mock firestore_client functions."""
    mock_get_races = MagicMock()
    # We still return a tuple to match test unpacking, but the second value is unused
    monkeypatch.setattr(firestore_client, "get_races_for_date", mock_get_races)
    return mock_get_races, MagicMock()


def test_get_pronostics_page(client):
    """Test that the main UI page loads."""
    response = client.get("/pronostics")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Hippique Orchestrator - Pronostics</title>" in response.text


def test_get_pronostics_data_empty_case(client, mock_plan, mock_firestore):
    """
    Test /api/pronostics when no races are in the plan or DB.
    It should return a valid "empty" response, not an error.
    """
    mock_get_races, _ = mock_firestore
    mock_plan.return_value = []
    mock_get_races.return_value = []

    response = client.get("/api/pronostics?date=2025-01-01")

    assert response.status_code == 200
    data = response.json()

    assert data["ok"] is True
    assert data["date"] == "2025-01-01"
    assert data["source"] == "empty"
    assert "No races found" in data["reason_if_empty"]
    assert data["counts"]["total_in_plan"] == 0
    assert data["counts"]["total_processed"] == 0
    assert len(data["pronostics"]) == 0

    # Check that last_updated is a valid ISO 8601 timestamp
    assert "last_updated" in data
    try:
        datetime.fromisoformat(data["last_updated"])
    except (ValueError, TypeError):
        pytest.fail("last_updated is not a valid ISO 8601 string")


def test_get_pronostics_data_etag_304_not_modified(client, mock_plan, mock_firestore, monkeypatch):
    """
    Test that the /api/pronostics endpoint returns a 304 Not Modified when the
    ETag matches, indicating the client's cache is fresh.
    """
    mock_get_races, _ = mock_firestore
    mock_plan.return_value = [{"r_label": "R1", "c_label": "C1"}]
    mock_get_races.return_value = []

    # Freeze time to ensure the ETag hash is the same
    frozen_time = datetime.now(timezone.utc)
    mock_datetime = MagicMock()
    mock_datetime.now.return_value = frozen_time
    monkeypatch.setattr("hippique_orchestrator.service.datetime", mock_datetime)

    # First request to get the ETag
    response1 = client.get("/api/pronostics?date=2025-01-01")
    assert response1.status_code == 200
    etag = response1.headers.get("etag")
    assert etag is not None

    # Second request with the ETag
    response2 = client.get("/api/pronostics?date=2025-01-01", headers={"If-None-Match": etag})
    assert response2.status_code == 304


def test_get_pronostics_data_with_data(client, mock_plan, mock_firestore):
    """
    Test /api/pronostics with data from both the plan and Firestore.
    """
    mock_get_races, _ = mock_firestore

    # Mock plan returns two races
    mock_plan.return_value = [
        {"r_label": "R1", "c_label": "C1", "name": "Prix d'Amerique"},
        {"r_label": "R1", "c_label": "C2", "name": "Prix de l'Arc"},
    ]

    # Mock firestore returns one processed race
    mock_doc = MagicMock()
    mock_doc.id = "2025-01-01_R1C1"
    mock_doc.to_dict.return_value = {
        "rc": "R1C1",
        "nom": "Prix d'Amerique",
        "status": "playable",
        "gpi_decision": "play_gpi",
        "last_analyzed_at": datetime.now().isoformat(),
        "tickets_analysis": {"gpi_decision": "play_gpi"},
    }
    mock_get_races.return_value = [mock_doc]

    response = client.get("/api/pronostics?date=2025-01-01")

    assert response.status_code == 200
    data = response.json()

    assert data["ok"] is True
    assert data["counts"]["total_in_plan"] == 2
    assert data["counts"]["total_processed"] == 1
    assert data["counts"]["total_playable"] == 1
    assert data["counts"]["total_pending"] == 1
    assert len(data["pronostics"]) == 2

    # Find the processed and pending races
    p_race = next((p for p in data["pronostics"] if p["rc"] == "R1C1"), None)
    u_race = next((p for p in data["pronostics"] if p["rc"] == "R1C2"), None)

    assert p_race is not None
    assert p_race["status"] == "playable"
    assert u_race is not None
    assert u_race["status"] == "pending"


def test_get_ops_status(client, mock_plan, mock_firestore):
    """Test the /ops/status endpoint with a standard scenario."""
    mock_get_races, _ = mock_firestore

    mock_plan.return_value = [{"r_label": "R1", "c_label": "C1"}]

    mock_doc = MagicMock()
    mock_doc.id = "2025-01-01_R1C1"
    mock_doc.update_time = datetime.now()
    mock_doc.to_dict.return_value = {
        "rc": "R1C1",
        "tickets_analysis": {"gpi_decision": "play_gpi"},
    }
    mock_get_races.return_value = [mock_doc]

    response = client.get("/ops/status?date=2025-01-01")

    assert response.status_code == 200
    data = response.json()

    assert data["date"] == "2025-01-01"
    assert data["config"]["firestore_collection"] == "races-test"
    assert data["counts"]["total_in_plan"] == 1
    assert data["counts"]["total_processed"] == 1
    assert data["counts"]["total_playable"] == 1
    assert data["firestore_metadata"]["docs_count_for_date"] == 1
    assert data["reason_if_empty"] is None


def test_get_ops_status_reason_if_empty(client, mock_plan, mock_firestore):
    """Test that /ops/status provides a reason when no races are processed."""
    mock_get_races, _ = mock_firestore

    # Plan has races, but firestore is empty
    mock_plan.return_value = [{"r_label": "R1", "c_label": "C1"}]
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


def test_post_ops_run_success(client, monkeypatch, mock_plan):
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
    mock_plan.return_value = [
        {
            "r_label": "R1",
            "c_label": "C1",
            "name": "Prix d'Amerique",
            "url": "http://example.com/r1c1",
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
async def test_run_single_race_missing_course_url(client, monkeypatch, mock_plan):
    """
    Test POST /ops/run when the target race in the plan is missing a course_url.
    """
    # Setup mock plan to return a race without a URL
    mock_plan.return_value = [
        {"r_label": "R1", "c_label": "C1", "name": "Prix d'Amerique", "url": None}
    ]

    # Make the request with a valid API key
    response = client.post("/ops/run?rc=R1C1", headers={"X-API-Key": "test-secret"})

    assert response.status_code == 400
    assert "Race R1C1 is missing a URL in the plan." in response.json()["detail"]
    mock_plan.assert_called_once()

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
async def test_schedule_day_races_success(client, monkeypatch, mock_plan):
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

    mock_plan.return_value = [{"r_label": "R1", "c_label": "C1"}]

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

    mock_plan.assert_called_once_with("2025-01-01")
    mock_scheduler.assert_called_once()

    # Check that force and dry_run flags were passed correctly
    _, kwargs = mock_scheduler.call_args
    assert kwargs["force"] is True
    assert kwargs["dry_run"] is True


@pytest.mark.asyncio
async def test_schedule_day_races_empty_plan(client, monkeypatch, mock_plan):
    """
    Test POST /schedule when the daily plan is empty.
    """
    mock_scheduler = MagicMock()
    monkeypatch.setattr("hippique_orchestrator.scheduler.schedule_all_races", mock_scheduler)
    mock_plan.return_value = []

    response = client.post(
        "/schedule",
        json={"date": "2025-01-01"},
        headers={"X-API-Key": "test-secret"},
    )

    assert response.status_code == 200
    assert "No races found in plan" in response.json()["message"]
    mock_scheduler.assert_not_called()


@pytest.mark.asyncio
async def test_run_single_race_unhandled_exception(client, monkeypatch, mock_plan):
    """
    Test POST /ops/run for an unhandled exception during the analysis pipeline.
    """
    # Setup mock plan to return the target race
    mock_plan.return_value = [
        {
            "r_label": "R1",
            "c_label": "C1",
            "name": "Prix d'Amerique",
            "url": "http://example.com/r1c1",
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
async def test_schedule_day_races_unhandled_exception(client, monkeypatch, mock_plan, caplog):
    """
    Test POST /schedule for an unhandled exception during processing.
    """
    # Simulate an unexpected error in build_plan_async
    mock_plan.side_effect = Exception("Simulated unhandled error")

    with caplog.at_level(logging.ERROR):
        response = client.post(
            "/schedule",
            json={"force": False, "dry_run": True, "date": "2025-01-01"},
            headers={"X-API-Key": "test-secret"},
        )

    assert response.status_code == 500
    assert "An internal error occurred" in response.json()["detail"]
    assert "UNHANDLED EXCEPTION in /schedule endpoint" in caplog.text
    mock_plan.assert_called_once()




def mock_get_races_for_date(*args, **kwargs):
    races = [
        {
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
        {
            "course_id": "2025-01-01_R1C2",
            "reunion": 1,
            "course": 2,
            "speciality": "Haies",
            "category": "Listed",
            "hippodrome": "Deauville",
            "start_time": "2025-01-01T14:20:00Z",
            "partants": 12,
            "tickets_analysis": {"gpi_decision": "abstention"},
        },
    ]

    mock_races = []
    for race_data in races:
        mock_race = Mock()
        mock_race.to_dict.return_value = race_data
        mock_race.id = race_data["course_id"]
        mock_races.append(mock_race)

    return mock_races


def test_api_pronostics_schema(client, monkeypatch):
    """
    Test the schema of the /api/pronostics endpoint.
    """
    monkeypatch.setattr(
        "hippique_orchestrator.firestore_client.get_races_for_date", mock_get_races_for_date
    )

    response = client.get("/api/pronostics?date=2025-01-01")
    assert response.status_code == 200
    data = response.json()

    assert "pronostics" in data
    assert isinstance(data["pronostics"], list)
    assert "last_updated" in data
    assert "version" in data

    for pronostic in data["pronostics"]:
        validate_pronostic(pronostic)


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


def test_run_single_race_not_found(client, mock_plan):
    """Test POST /ops/run when the requested race is not in the plan."""
    mock_plan.return_value = [{"r_label": "R1", "c_label": "C2", "name": "Some Other Race"}]
    response = client.post("/ops/run?rc=R1C1", headers={"X-API-Key": "test-secret"})
    assert response.status_code == 404
    assert "Race R1C1 not found" in response.json()["detail"]


def test_get_daily_plan_success(client, mock_plan):
    """Test a successful call to the /api/plan endpoint."""
    mock_plan.return_value = [{"r_label": "R1", "c_label": "C1"}]
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


def test_get_pronostics_data_defaults_to_today(client, mock_plan, mock_firestore):
    """Test /api/pronostics defaults to the current date when none is provided."""
    mock_get_races, _ = mock_firestore
    mock_plan.return_value = []
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


def test_api_pronostics_schema_and_ui_markers(client, monkeypatch):
    """
    Test the schema of /api/pronostics and that the UI contains critical markers.
    """
    # 1. Test API Schema
    monkeypatch.setattr(
        "hippique_orchestrator.firestore_client.get_races_for_date", mock_get_races_for_date
    )

    api_response = client.get("/api/pronostics?date=2025-01-01")
    assert api_response.status_code == 200
    data = api_response.json()

    assert "pronostics" in data and isinstance(data["pronostics"], list)
    assert "last_updated" in data and "version" in data

    for pronostic in data["pronostics"]:
        validate_pronostic(pronostic)

    # 2. Test UI Content
    ui_response = client.get("/pronostics")
    assert ui_response.status_code == 200
    html = ui_response.text

    assert '<table id="races-table">' in html
    assert '<tbody id="races-tbody">' in html
    assert 'fetch(`/api/pronostics?date=${date}`)' in html
