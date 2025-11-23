
import json
import pathlib
import shutil
import sys

import pytest
import os
from unittest.mock import MagicMock, patch
import httpx

from fastapi.testclient import TestClient

# --- Add project root to sys.path ---
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.service import app

client = TestClient(app)

@pytest.fixture(scope="module")
def setup_test_data():
    data_dir = _PROJECT_ROOT / "data"
    race_dir = data_dir / "R1C1"
    race_dir.mkdir(parents=True, exist_ok=True)

    # Create a dummy analysis file
    analysis_data = {
        "reunion": "R1",
        "course": "C1",
        "abstain": False,
        "tickets": [
            {"type": "SP", "detail": "3-5", "mise": 2.0},
            {"type": "CG", "detail": "3-5-7", "mise": 3.0}
        ],
        "validation": {
            "roi_global_est": 25.0
        }
    }
    with open(race_dir / "analysis_H5.json", "w") as f:
        json.dump(analysis_data, f)

    yield

    # Teardown
    shutil.rmtree(race_dir)

    def test_health_check():
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
def xtest_pipeline_run_success(mocker):
    # This test verifies the file-reading logic of the endpoint.
    # We mock subprocess.run as it's not relevant to this path.
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "Pipeline executed successfully"
    mock_run.return_value.stderr = ""

    # Create a dummy analysis file for the endpoint to find
    data_dir = _PROJECT_ROOT / "data" / "R1C2"
    data_dir.mkdir(parents=True, exist_ok=True)
    analysis_data = {
        "abstain": False,
        "tickets": [{"type": "SP", "detail": "1-2", "mise": 5.0}],
        "validation": {"roi_global_est": 30.0}
    }
    with open(data_dir / "analysis_H5.json", "w") as f:
        json.dump(analysis_data, f)

    response = client.post("/pipeline/run?use_file_logic=true", json={"reunion": "R1", "course": "C2", "phase": "H5", "budget": 5.0})

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == "ok"
    assert not response_json["abstain"]
    assert len(response_json["tickets"]) == 1
    assert response_json["roi_global_est"] == 30.0

    # Teardown
    shutil.rmtree(data_dir)

def xtest_tickets_endpoint(setup_test_data):
    response = client.get("/tickets")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "<h1>Today's Tickets</h1>" in content
    assert "<h2>R1C1</h2>" in content
    assert "ROI Global Est: 25.0%" in content
    assert "<li>SP - 3-5 - 2.0€</li>" in content
    assert "<li>CG - 3-5-7 - 3.0€</li>" in content


def test_run_endpoint_success(mocker):
    """
    Vérifie que le point de terminaison /run traite une requête valide avec succès.
    """
    # Mock la fonction run_course pour isoler le test de l'exécution réelle
    mock_run = mocker.patch("src.service.run_course", return_value={"ok": True, "phase": "H-5"})
    
    payload = {
        "course_url": "https://www.zeturf.fr/fr/course/2025-10-20/R1C2-marseille-borely/details",
        "phase": "H-5",
        "date": "2025-10-20"
    }
    response = client.post("/run", json=payload)

    assert response.status_code == 200
    mock_run.assert_called_once()
    assert response.json()["ok"] is True


def test_schedule_endpoint_success(mocker):
    """
    Vérifie que le point de terminaison /schedule traite une requête valide avec succès.
    """
    # Mock l'appel interne à bootstrap-day pour isoler le test
    mock_post = mocker.patch("httpx.AsyncClient.post")
    mock_post.return_value = httpx.Response(202, json={"ok": True, "message": "Bootstrap initiated."})

    response = client.post("/schedule", json={"date": "2025-10-20", "mode": "tasks"})

    assert response.status_code == 202
    assert response.json()["ok"] is True


def test_schedule_endpoint_handles_scheduling_error(mocker):
    """
    Vérifie que le point de terminaison /schedule gère les erreurs de l'ordonnanceur.
    """
    # Mock l'appel interne pour qu'il renvoie une erreur
    mock_post = mocker.patch("httpx.AsyncClient.post")
    mock_post.return_value = httpx.Response(500, json={"ok": False, "error": "Internal bootstrap failed."})

    response = client.post("/schedule", json={"date": "today", "mode": "tasks"})

    assert response.status_code == 500
    assert response.json()["ok"] is False
    assert "bootstrap failed" in response.json()["error"]

def test_debug_parse_endpoint(mocker):
    """
    Vérifie que le point de terminaison /debug/parse fonctionne correctement.
    """
    mock_build_plan = mocker.patch("src.plan.build_plan_async")
    mock_build_plan.return_value = [{"reunion": "R1", "course": "C1", "details": "Test Race"}]

    response = client.get("/debug/parse?date=2025-01-01")

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["ok"] is True
    assert response_json["count"] == 1
    assert response_json["races"][0]["details"] == "Test Race"
    mock_build_plan.assert_called_once_with("2025-01-01")
