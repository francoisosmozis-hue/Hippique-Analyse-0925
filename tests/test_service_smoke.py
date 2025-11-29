from fastapi.testclient import TestClient
from hippique_orchestrator.service import app
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
# The middleware itself checks `config.require_auth`. We can patch that.
from src.config.config import config
config.require_auth = False

client = TestClient(app)

def test_health_check():
    """Tests if the /healthz endpoint is reachable and returns OK."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_pronostics_endpoint_returns_ok_when_no_data(tmp_path: Path):
    """
    Tests that the /api/pronostics endpoint returns an OK response (but with no data)
    when no pronostics file is found for the given date.
    """
    date_str = "2025-11-28"
    # Patch the ANALYSES_DIR to use our temporary directory
    with patch('hippique_orchestrator.service.ANALYSES_DIR', tmp_path):
        response = client.get(f"/api/pronostics?date={date_str}")
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["ok"] is False
        assert response_data["total_races"] == 0
        assert "No pronostics found for date" in response_data["message"]

def test_pronostics_endpoint_returns_data_when_file_exists(tmp_path: Path):
    """
    Tests that the /api/pronostics endpoint successfully returns data
    when a valid pronostics file is present.
    """
    date_str = "2025-11-28"
    
    # Setup: Create a dummy analysis file in a subdirectory
    race_dir = tmp_path / "R1C1"
    race_dir.mkdir()
    dummy_file = race_dir / f"{date_str}_R1C1_H5.json"
    dummy_data = {"race": "R1C1", "pronostics": [1, 2, 3]}
    with open(dummy_file, "w") as f:
        json.dump(dummy_data, f)

    # Patch the ANALYSES_DIR to use our temporary directory
    with patch('hippique_orchestrator.service.ANALYSES_DIR', tmp_path):
        response = client.get(f"/api/pronostics?date={date_str}")
        assert response.status_code == 200
        
        response_data = response.json()
        assert response_data["ok"] is True
        assert response_data["total_races"] == 1
        assert len(response_data["pronostics"]) == 1
        assert response_data["pronostics"][0]["race"] == "R1C1"
        assert response_data["pronostics"][0]["pronostics"] == [1, 2, 3]
