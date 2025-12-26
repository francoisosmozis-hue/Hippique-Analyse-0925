from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# Mock the firestore client before it's imported by the service
from hippique_orchestrator import firestore_client
firestore_client.db = MagicMock()

from hippique_orchestrator.service import app

client = TestClient(app)

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
    mock_get_status = MagicMock()
    monkeypatch.setattr(firestore_client, "get_races_for_date", mock_get_races)
    monkeypatch.setattr(firestore_client, "get_processing_status_for_date", mock_get_status)
    return mock_get_races, mock_get_status

def test_get_pronostics_page():
    """Test that the main UI page loads."""
    response = client.get("/pronostics")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Hippique Orchestrator - Pronostics</title>" in response.text

def test_get_pronostics_data_empty_case(mock_plan, mock_firestore):
    """
    Test /api/pronostics when no races are in the plan or DB.
    It should return a valid "empty" response, not an error.
    """
    mock_build_plan, _ = mock_plan, mock_firestore
    mock_build_plan.return_value = []
    mock_get_races, _ = mock_firestore
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

def test_get_pronostics_data_with_data(mock_plan, mock_firestore):
    """
    Test /api/pronostics with data from both the plan and Firestore.
    """
    mock_build_plan, (mock_get_races, _) = mock_plan, mock_firestore
    
    # Mock plan returns two races
    mock_build_plan.return_value = [
        {"rc_label": "R1C1", "name": "Prix d'Amerique"},
        {"rc_label": "R1C2", "name": "Prix de l'Arc"},
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
        "tickets_analysis": {"gpi_decision": "play_gpi"}
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

def test_get_ops_status(mock_plan, mock_firestore):
    """Test the /api/ops/status endpoint."""
    _, (mock_get_races, mock_get_status) = mock_plan, mock_firestore
    
    mock_get_status.return_value = {
        "date": "2025-01-01",
        "summary": {"total_in_plan": 1, "total_processed": 0, "playable": 0, "abstain": 0, "errors": 0},
        "races": [{"rc": "R1C1", "name": "Prix de Test", "status": "Not Processed"}],
    }

    response = client.get("/ops/status?date=2025-01-01")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["date"] == "2025-01-01"
    assert data["summary"]["total_in_plan"] == 1
    assert len(data["races"]) == 1

def test_health_check():
    """Test the /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data