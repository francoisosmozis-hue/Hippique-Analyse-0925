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

def test_health_check(client):
    """Tests if the /healthz endpoint is reachable and returns OK."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_pronostics_endpoint_returns_ok_when_no_data(client, mocker):
    """
    Tests that the /api/pronostics endpoint returns an OK response (but with no data)
    when no pronostics are found in Firestore for the given date.
    """
    date_str = "2025-11-28"
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[])
    
    response = client.get(f"/api/pronostics?date={date_str}")
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["ok"] is True
    assert response_data["total_races"] == 0
    assert "No pronostics found for date" in response_data["message"]

def test_pronostics_endpoint_returns_data_when_file_exists(client, mocker):
    """
    Tests that the /api/pronostics endpoint successfully returns data
    when a valid pronostics document is present in Firestore.
    """
    date_str = "2025-11-28"
    dummy_data = {"race": "R1C1", "pronostics": [1, 2, 3]}
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[
        {"id": f"{date_str}_R1C1", "tickets_analysis": dummy_data}
    ])

    response = client.get(f"/api/pronostics?date={date_str}")
    assert response.status_code == 200
    
    response_data = response.json()
    assert response_data["ok"] is True
    assert response_data["total_races"] == 1
    assert len(response_data["pronostics"]) == 1
    assert response_data["pronostics"][0]["race"] == "R1C1"
    assert response_data["pronostics"][0]["pronostics"] == [1, 2, 3]
