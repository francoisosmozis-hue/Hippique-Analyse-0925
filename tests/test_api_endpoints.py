# tests/test_api_endpoints.py
import pytest
from datetime import datetime
from freezegun import freeze_time
from hippique_orchestrator.service import bootstrap_day_pipeline

@pytest.fixture
def client(client):
    """Override the default client fixture to handle specific setups if needed."""
    # This is a good place to apply application-wide mocks or settings
    return client

# Test 1: Health check endpoint
def test_healthz_endpoint(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert "service" in response.json()

# Test 2: Pronostics endpoint with no data
def test_api_pronostics_no_data(client, mocker):
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[])
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    response = client.get(f"/api/pronostics?date={mock_date_str}")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 0
    assert data["pronostics"] == []

# Test 3: Pronostics endpoint with valid mock data
def test_api_pronostics_with_mock_data(client, mocker):
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    
    # This structure simulates a raw document from Firestore
    mock_firestore_doc = {
        "id": f"{mock_date_str}_R1C1",
        "rc": "R1C1", # 'rc' is a top-level field in the Firestore doc
        "tickets_analysis": {
            "gpi_decision": "Play",
            "tickets": [{"type": "SP", "cheval": "1"}],
            "roi_global_est": 0.2
        }
    }
    
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[mock_firestore_doc])

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 1
    assert len(data["pronostics"]) == 1
    
    # Assert the structure transformed by the API endpoint
    prono = data["pronostics"][0]
    assert prono["rc"] == "R1C1"
    assert prono["gpi_decision"] == "Play"
    assert prono["tickets"][0]["type"] == "SP"

# Test 4: Graceful handling of malformed documents
def test_api_pronostics_handles_malformed_doc(client, mocker):
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    
    # A valid document
    valid_doc = {
        "id": f"{mock_date_str}_R1C1",
        "rc": "R1C1",
        "tickets_analysis": {"gpi_decision": "Play", "tickets": []}
    }
    # A malformed document (missing 'tickets_analysis')
    malformed_doc = {
        "id": f"{mock_date_str}_R1C2",
        "rc": "R1C2",
        "some_other_field": {}
    }
    
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[valid_doc, malformed_doc])

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    # Only the valid document should be counted and returned
    assert data["total_races"] == 1
    assert len(data["pronostics"]) == 1
    assert data["pronostics"][0]["rc"] == "R1C1"

# Test 5: Aggregation of multiple valid documents
def test_api_pronostics_aggregates_multiple_docs(client, mocker):
    mock_date_str = datetime.now().strftime("%Y-%m-%d")
    
    doc1 = {"id": f"{mock_date_str}_R1C1", "rc": "R1C1", "tickets_analysis": {"gpi_decision": "Play", "tickets": []}}
    doc2 = {"id": f"{mock_date_str}_R1C2", "rc": "R1C2", "tickets_analysis": {"gpi_decision": "Abstain", "tickets": []}}

    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_by_date_prefix", return_value=[doc1, doc2])

    response = client.get(f"/api/pronostics?date={mock_date_str}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 2
    assert len(data["pronostics"]) == 2
    assert {p["rc"] for p in data["pronostics"]} == {"R1C1", "R1C2"}

# Test 6: Invalid date format
def test_api_pronostics_invalid_date_format(client):
    response = client.get("/api/pronostics?date=not-a-date")
    assert response.status_code == 422
    assert "invalid date format" in response.json()["detail"].lower()

# Test 7: Bootstrap day task endpoint
@freeze_time("2025-11-24")
def test_tasks_bootstrap_day(client, mocker):
    mock_add_task = mocker.patch("fastapi.BackgroundTasks.add_task")
    mock_date_str = datetime.now().strftime("%Y-%m-%d")

    response = client.post("/tasks/bootstrap-day", json={"date": mock_date_str})

    assert response.status_code == 202
    assert response.json()["ok"] is True
    
    mock_add_task.assert_called_once()
    call_args, call_kwargs = mock_add_task.call_args
    assert call_args[0] == bootstrap_day_pipeline
    assert call_kwargs["date_str"] == mock_date_str

# Test 8: Run phase task endpoint
async def test_tasks_run_phase(client, mocker):
    mocker.patch("hippique_orchestrator.service.run_course", return_value={"ok": True, "phase": "H5", "artifacts": []})
    mock_date_str = datetime.now().strftime("%Y-%m-%d")

    response = client.post("/tasks/run-phase", json={
        "course_url": "http://example.com/R1C1",
        "phase": "H5",
        "date": mock_date_str
    })
    assert response.status_code == 200
    assert response.json()["ok"] is True
