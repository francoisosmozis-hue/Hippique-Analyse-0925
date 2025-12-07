import json
from unittest.mock import patch
from pathlib import Path

# Disable authentication for testing by overriding the dependency
async def override_auth():
    pass

# In service.py, the middleware is `verify_oidc_token`
# We need to find what dependency it uses or disable it entirely.
# A simpler way for TestClient is to override the dependency that requires auth.
# Let's assume there's a dependency that provides the user or validates the token.
# After inspecting service.py, there is no named dependency, it's a pure middleware.
# The middleware itself checks `config.REQUIRE_AUTH`. We can patch that.
# global client is removed, now handled by conftest.py

def test_ping(client):
    """Tests if the /ping endpoint is reachable and returns OK."""
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "pong"}

def test_health_check(client):
    """Tests if the /healthz endpoint is reachable and returns OK."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_pronostics_endpoint_returns_ok_when_no_data(client, mocker):
    """
    Tests that the /pronostics endpoint returns an OK response (but with no data)
    when no pronostics are found in Firestore for the given date.
    """
    date_str = "2025-11-28"
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[])
    
    response = client.get(f"/pronostics?date={date_str}")
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["ok"] is True
    assert response_data["total_races"] == 0
    assert response_data["pronostics"] == []

def test_pronostics_endpoint_returns_data_when_file_exists(client, mocker):
    """
    Tests that the /pronostics endpoint successfully returns data
    when a valid pronostics document is present in Firestore, matching the new API structure.
    """
    date_str = "2025-11-28"
    # This mock simulates the data structure stored in Firestore
    mock_firestore_doc = {
        "id": f"{date_str}_R1C1",
        "rc": "R1C1",
        "tickets_analysis": {
            "gpi_decision": "Play",
            "tickets": [{"type": "SP", "cheval": "1", "mise": 5.0}],
            "roi_global_est": 0.25
        }
    }
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[mock_firestore_doc])

    response = client.get(f"/pronostics?date={date_str}")
    assert response.status_code == 200
    
    response_data = response.json()
    assert response_data["ok"] is True
    assert response_data["total_races"] == 1
    
    # Assert the new, corrected structure
    pronostic = response_data["pronostics"][0]
    assert pronostic["rc"] == "R1C1"
    assert pronostic["gpi_decision"] == "Play"
    assert len(pronostic["tickets"]) == 1
    assert pronostic["tickets"][0]["cheval"] == "1"

