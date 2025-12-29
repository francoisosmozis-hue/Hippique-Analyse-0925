from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# Mock the firestore client before it's imported by the service
from hippique_orchestrator import firestore_client

firestore_client.db = MagicMock()

from hippique_orchestrator.service import app  # noqa: E402




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
    monkeypatch.setattr("hippique_orchestrator.firestore_client.update_race_document", mock_update_db)

    # Setup mock plan to return the target race
    mock_plan.return_value = [
        {"r_label": "R1", "c_label": "C1", "name": "Prix d'Amerique", "url": "http://example.com/r1c1"}
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


def test_pronostics_api_security(mocker, mock_plan, mock_firestore):
    """
    Tests that the /api/pronostics endpoint is properly secured with an API key.
    This test creates its own client to ensure dependency overrides don't leak.
    """
    # Enable auth for this specific test, overriding the default test config
    mocker.patch("hippique_orchestrator.config.REQUIRE_AUTH", True)

    # Re-import the app and create a new client AFTER patching the config
    from hippique_orchestrator.service import app
    from fastapi.testclient import TestClient
    
    with TestClient(app) as client:
        # Mock the underlying functions to isolate the auth logic
        mock_get_races, _ = mock_firestore
        mock_plan.return_value = []
        mock_get_races.return_value = []

        # 1. Test without API key -> should fail (403 Forbidden)
        response_no_key = client.get("/api/pronostics?date=2025-01-01")
        assert response_no_key.status_code == 403
        assert "Invalid or missing API Key" in response_no_key.json()["detail"]

        # 2. Test with incorrect API key -> should fail (403 Forbidden)
        response_wrong_key = client.get(
            "/api/pronostics?date=2025-01-01", headers={"X-API-Key": "wrong-secret"}
        )
        assert response_wrong_key.status_code == 403
        assert "Invalid or missing API Key" in response_wrong_key.json()["detail"]

        # 3. Test with correct API key -> should succeed (200 OK)
        response_good_key = client.get(
            "/api/pronostics?date=2025-01-01", headers={"X-API-Key": "test-secret"}
        )
        assert response_good_key.status_code == 200

