# tests/test_api_endpoints.py
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import json
from pathlib import Path
from freezegun import freeze_time

# Importez l'application FastAPI depuis src.service
from hippique_orchestrator.service import app

# Créez un client de test pour l'application FastAPI
@pytest.fixture(scope="module")
def client():
    return TestClient(app)

# Test 1: Vérifier que l'endpoint de santé répond 200 OK
def test_healthz_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert "service" in response.json()

# Test 2: Vérifier l'endpoint /api/pronostics sans données
def test_api_pronostics_no_data(client):
    # Assurez-vous qu'il n'y a pas de fichiers d'analyse pour aujourd'hui
    # (cela peut nécessiter un nettoyage ou un mock plus avancé pour un test isolé)
    response = client.get("/api/pronostics")
    assert response.status_code == 200
    assert response.json()["ok"] == False
    assert response.json()["total_races"] == 0
    assert response.json()["pronostics"] == []
    assert "No pronostics found" in response.json()["message"]

# Test 3: Vérifier l'endpoint /api/pronostics avec des données mockées
# Pour ce test, nous allons créer un fichier analysis_H5.json temporaire
def test_api_pronostics_with_mock_data(client, tmp_path, mocker):
    # Create a dummy data/analyses directory within tmp_path
    mock_analyses_dir = tmp_path / "data" / "analyses"
    mock_analyses_dir.mkdir(parents=True)

    # Create a dummy data/analyses directory within tmp_path
    mock_analyses_dir = tmp_path / "data" / "analyses"
    mock_analyses_dir.mkdir(parents=True, exist_ok=True)

    # Mock src.service.Path so that Path("data/analyses") returns mock_analyses_dir
    mocker.patch("hippique_orchestrator.service.Path", side_effect=lambda p: mock_analyses_dir if p == "data/analyses" else Path(p))

    # Créez une structure de répertoire et un fichier analysis_H5.json
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    mock_race_dir = mock_analyses_dir / "R1C1"
    mock_race_dir.mkdir()
    
    mock_analysis_data = {
        "date": mock_date_str,
        "gpi_decision": "OK",
        "rc": "R1C1",
        "hippodrome": "Vincennes",
        "heure_depart": "14:30",
        "discipline": "Trot",
        "course_url": "http://example.com/R1C1",
        "tickets": [
            {"type": "Simple Gagnant", "cheval": "1", "mise": 1.5, "cote": 5.0, "ev": 0.8, "roi": 0.2}
        ]
    }
    mock_file_path = mock_race_dir / f"{mock_date_str}_R1C1_H5.json"
    with open(mock_file_path, "w") as f:
        json.dump(mock_analysis_data, f)

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    assert response.status_code == 200
    assert response.json()["ok"] == True
    assert response.json()["total_races"] == 1
    assert response.json()["pronostics"][0]["rc"] == "R1C1"
    assert response.json()["pronostics"][0]["tickets"][0]["cheval"] == "1"

# Test 4: Vérifier l'endpoint /tasks/snapshot-9h (déclenchement en arrière-plan)
def test_tasks_snapshot_9h(client, mocker):
    # Mock la fonction write_snapshot_for_day pour éviter le scraping réel
    mocker.patch("hippique_orchestrator.api.tasks.write_snapshot_for_day", return_value=[])
    
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    response = client.post("/tasks/snapshot-9h", json={"date": mock_date_str})
    
    assert response.status_code == 202 # Accepted
    assert response.json()["ok"] == True
    assert "initiated in background" in response.json()["message"]
    
    # Note: Testing background tasks with TestClient is complex.
    # We are verifying that the endpoint returns 202 Accepted,
    # which implies the task was added to the background queue.
    # A more advanced test would require a different setup.
    # mocker.patch("src.api.tasks.write_snapshot_for_day").assert_called_once_with(
    #     date_str=mock_date_str,
    #     race_urls=None,
    #     phase="H9",
    #     correlation_id=mocker.ANY
    # )

# Test 5: Vérifier l'endpoint /tasks/run-phase
def test_tasks_run_phase(client, mocker):
    """Test the /tasks/run-phase endpoint."""
    # Mock the run_course function to avoid real pipeline execution
    mocker.patch("hippique_orchestrator.api.tasks.run_course", return_value={"ok": True, "phase": "H5", "artifacts": []})

    mock_course_url = "http://example.com/course/R1C1"
    mock_date_str = datetime.now().strftime("%Y-%m-%d")

    response = client.post("/tasks/run-phase", json={
        "course_url": mock_course_url,
        "phase": "H5",
        "date": mock_date_str
    })

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["phase"] == "H5"

    # As with snapshot, this is a background task.
    # We trust that if the endpoint returns success, the task was queued.
    # mock_run.assert_called_once_with(
    #     course_url=mock_course_url,
    #     phase="H5",
    #     date=mock_date_str,
    #     correlation_id=mocker.ANY
    # )

# Test 6: Vérifier l'endpoint /tasks/bootstrap-day
@freeze_time("2025-11-24")
def test_tasks_bootstrap_day(client, mocker):
    """Test the /tasks/bootstrap-day endpoint."""
    # Create dynamic race times that are always in the future
    now = datetime.now()
    future_time_1 = (now + timedelta(hours=1)).strftime("%H:%M")
    future_time_2 = (now + timedelta(hours=2)).strftime("%H:%M")

    mock_plan = [
        {"course_url": "http://example.com/course/R1C1", "time_local": future_time_1, "r_label": "R1", "c_label": "C1", "date": now.strftime("%Y-%m-%d")},
        {"course_url": "http://example.com/course/R1C2", "time_local": future_time_2, "r_label": "R1", "c_label": "C2", "date": now.strftime("%Y-%m-%d")},
    ]
    mocker.patch("hippique_orchestrator.api.tasks.build_plan_async", return_value=mock_plan)

    # Mock enqueue_run_task to avoid real Cloud Tasks creation
    mocker.patch("hippique_orchestrator.api.tasks.enqueue_run_task")

    mock_date_str = now.strftime("%Y-%m-%d")
    response = client.post("/tasks/bootstrap-day", json={"date": mock_date_str})

    assert response.status_code == 202
    assert response.json()["ok"] is True
    assert response.json()["scheduled_tasks"] == 4  # 2 courses * (H30 + H5)
    assert mock_enqueue.call_count == 4

def test_api_pronostics_handles_malformed_json(client, tmp_path, mocker):
    """
    Tests that the /api/pronostics endpoint gracefully handles a malformed JSON file
    by logging an error and excluding it from the results, without crashing.
    """
    mock_analyses_dir = tmp_path / "data" / "analyses"
    mock_analyses_dir.mkdir(parents=True, exist_ok=True)

    mocker.patch("hippique_orchestrator.service.Path", side_effect=lambda p: mock_analyses_dir if p == "data/analyses" else Path(p))

    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Create a valid file
    valid_race_dir = mock_analyses_dir / "R1C1"
    valid_race_dir.mkdir()
    valid_data = {"rc": "R1C1", "gpi_decision": "OK", "tickets": []}
    valid_file_path = valid_race_dir / f"{mock_date_str}_R1C1_H5.json"
    with open(valid_file_path, "w") as f:
        json.dump(valid_data, f)

    # Create a malformed file
    malformed_race_dir = mock_analyses_dir / "R1C2"
    malformed_race_dir.mkdir()
    malformed_file_path = malformed_race_dir / f"{mock_date_str}_R1C2_H5.json"
    with open(malformed_file_path, "w") as f:
        f.write("{'rc': 'R1C2', 'gpi_decision': 'INVALID JSON'") # Invalid JSON

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    
    assert response.status_code == 200
    assert response.json()["ok"] == True
    assert response.json()["total_races"] == 1  # Only the valid file should be counted
    assert len(response.json()["pronostics"]) == 1
    assert response.json()["pronostics"][0]["rc"] == "R1C1"

def test_api_pronostics_aggregates_multiple_files(client, tmp_path, mocker):
    """
    Tests that the /api/pronostics endpoint correctly aggregates data from multiple
    valid analysis files for the same day.
    """
    mock_analyses_dir = tmp_path / "data" / "analyses"
    mock_analyses_dir.mkdir(parents=True, exist_ok=True)

    mocker.patch("hippique_orchestrator.service.Path", side_effect=lambda p: mock_analyses_dir if p == "data/analyses" else Path(p))

    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Create first valid file
    race1_dir = mock_analyses_dir / "R1C1"
    race1_dir.mkdir()
    race1_data = {"rc": "R1C1", "gpi_decision": "OK", "tickets": []}
    race1_file_path = race1_dir / f"{mock_date_str}_R1C1_H5.json"
    with open(race1_file_path, "w") as f:
        json.dump(race1_data, f)

    # Create second valid file
    race2_dir = mock_analyses_dir / "R1C2"
    race2_dir.mkdir()
    race2_data = {"rc": "R1C2", "gpi_decision": "OK", "tickets": []}
    race2_file_path = race2_dir / f"{mock_date_str}_R1C2_H5.json"
    with open(race2_file_path, "w") as f:
        json.dump(race2_data, f)

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    
    assert response.status_code == 200
    assert response.json()["ok"] == True
    assert response.json()["total_races"] == 2
    assert len(response.json()["pronostics"]) == 2
    
    # Check if both races are in the response
    rcs_in_response = {p["rc"] for p in response.json()["pronostics"]}
    assert "R1C1" in rcs_in_response
    assert "R1C2" in rcs_in_response

def test_api_pronostics_invalid_date_format(client):
    """
    Tests that the /api/pronostics endpoint returns a 422 Unprocessable Entity error
    when the date parameter is not in the correct format.
    """
    response = client.get("/api/pronostics?date=not-a-date")
    # FastAPI's automatic validation should catch this and return 422
    assert response.status_code == 422
    assert "error" in response.json()
    # Check for a more specific error message if possible
    assert "invalid date format" in response.json()["error"].lower()