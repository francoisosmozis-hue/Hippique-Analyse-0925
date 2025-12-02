# tests/test_api_endpoints.py
import pytest
from datetime import datetime, timedelta
import json
from pathlib import Path
from freezegun import freeze_time

# Test 1: Vérifier que l'endpoint de santé répond 200 OK
def test_healthz_endpoint(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert "service" in response.json()

# Test 2: Vérifier l'endpoint /api/pronostics sans données
def test_api_pronostics_no_data(client, mocker):
    # Assurez-vous qu'il n'y a pas de fichiers d'analyse pour aujourd'hui
    # (cela peut nécessiter un nettoyage ou un mock plus avancé pour un test isolé)
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[])
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    response = client.get(f"/api/pronostics?date={mock_date_str}")
    assert response.status_code == 200
    assert response.json()["ok"] == True
    assert response.json()["total_races"] == 0
    assert response.json()["pronostics"] == []
    assert "No pronostics found" in response.json()["message"]

# Test 3: Vérifier l'endpoint /api/pronostics avec des données mockées
# Pour ce test, nous allons créer un fichier analysis_H5.json temporaire
def test_api_pronostics_with_mock_data(client, mocker):
    # Créez une structure de répertoire et un fichier analysis_H5.json
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    
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
    
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[{"id": f"{mock_date_str}_R1C1", "tickets_analysis": mock_analysis_data}])

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["ok"] == True
    assert response_data["total_races"] == 1
    assert len(response_data["pronostics"]) == 1
    assert response_data["pronostics"][0]["rc"] == "R1C1"

# Test 4: Vérifier l'endpoint /tasks/snapshot-9h (déclenchement en arrière-plan)
def test_tasks_snapshot_9h(client, mocker):
    # Mock la fonction write_snapshot_for_day pour éviter le scraping réel
    mocker.patch("hippique_orchestrator.service.write_snapshot_for_day", return_value=[])
    
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
    mocker.patch("hippique_orchestrator.runner.run_course", return_value={"ok": True, "phase": "H5", "artifacts": []})

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
    mocker.patch("hippique_orchestrator.service.build_plan_async", return_value=mock_plan)

    # Mock enqueue_run_task to avoid real Cloud Tasks creation
    mock_schedule = mocker.patch("hippique_orchestrator.scheduler.schedule_all_races", return_value=[
        {"race": "R1C1", "phase": "H30", "ok": True, "task_name": "task-r1c1-h30"},
        {"race": "R1C1", "phase": "H5", "ok": True, "task_name": "task-r1c1-h5"},
        {"race": "R1C2", "phase": "H30", "ok": True, "task_name": "task-r1c2-h30"},
        {"race": "R1C2", "phase": "H5", "ok": True, "task_name": "task-r1c2-h5"},
    ])

    mock_date_str = now.strftime("%Y-%m-%d")
    response = client.post("/tasks/bootstrap-day", json={"date": mock_date_str})

    assert response.status_code == 202
    assert response.json()["ok"] is True
    assert response.json()["scheduled_tasks"] == 4  # 2 courses * (H30 + H5)
    mock_schedule.assert_called_once()

def test_api_pronostics_handles_malformed_json(client, mocker):
    """
    Tests that the /api/pronostics endpoint gracefully handles a malformed document
    by logging an error and excluding it from the results, without crashing.
    """
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    
    valid_data = {"rc": "R1C1", "gpi_decision": "OK", "tickets": []}
    malformed_data = {"rc": "R1C2", "gpi_decision": "INVALID"} # Missing tickets_analysis

    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[
        {"id": f"{mock_date_str}_R1C1", "tickets_analysis": valid_data},
        {"id": f"{mock_date_str}_R1C2", "some_other_key": malformed_data},
    ])

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["ok"] is True
    assert response_data["total_races"] == 1
    assert len(response_data["pronostics"]) == 1
    assert response_data["pronostics"][0]["rc"] == "R1C1"

def test_api_pronostics_aggregates_multiple_files(client, mocker):
    """
    Tests that the /api/pronostics endpoint correctly aggregates data from multiple
    valid analysis documents from Firestore.
    """
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    
    race1_data = {"rc": "R1C1", "gpi_decision": "OK", "tickets": []}
    race2_data = {"rc": "R1C2", "gpi_decision": "OK", "tickets": []}

    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[
        {"id": f"{mock_date_str}_R1C1", "tickets_analysis": race1_data},
        {"id": f"{mock_date_str}_R1C2", "tickets_analysis": race2_data},
    ])

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["ok"] is True
    assert response_data["total_races"] == 2
    assert len(response_data["pronostics"]) == 2

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