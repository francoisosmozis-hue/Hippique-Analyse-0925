
import pytest

# NOTE: The client fixture is now provided by conftest.py

def test_healthz_endpoint(client):
    """Tests if the /healthz endpoint is reachable and returns OK."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_api_pronostics_no_data(client, mocker):
    """
    Tests that the /pronostics endpoint returns an OK response (but with no data)
    when no pronostics are found in Firestore for the given date.
    """
    mocker.patch("hippique_orchestrator.firestore_client.get_races_by_date_prefix", return_value=[])

    # Test without date parameter (uses default today)
    response = client.get("/pronostics")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 0
    assert data["pronostics"] == []
    assert "date" in data # Ensure date used is returned

    # Test with a specific date
    mock_date_str = "2025-12-07"
    response = client.get(f"/pronostics?date={mock_date_str}")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 0
    assert data["pronostics"] == []
    assert data["date"] == mock_date_str


def test_api_pronostics_with_mock_data(client, mocker):
    """
    Tests that the /pronostics endpoint successfully returns data
    when a valid pronostics document is present in Firestore, matching the new API structure.
    """
    mock_date_str = "2025-12-07"

    mock_firestore_doc = {
        "id": f"{mock_date_str}_R1C1",
        "rc": "R1C1",
        "tickets_analysis": {
            "gpi_decision": "Play",
            "tickets": [{"type": "SP", "cheval": "1"}],
            "roi_global_est": 0.2
        }
    }

    mocker.patch("hippique_orchestrator.firestore_client.get_races_by_date_prefix", return_value=[mock_firestore_doc])

    response = client.get(f"/pronostics?date={mock_date_str}")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 1
    assert data["date"] == mock_date_str

    pronostic = data["pronostics"][0]
    assert pronostic["rc"] == "R1C1"
    assert pronostic["gpi_decision"] == "Play"
    assert len(pronostic["tickets"]) == 1
    assert pronostic["tickets"][0]["type"] == "SP"


def test_api_pronostics_handles_malformed_doc(client, mocker):
    """
    Tests that the /pronostics endpoint gracefully handles Firestore documents
    that do not contain the expected 'tickets_analysis' field.
    """
    mock_date_str = "2025-12-07"

    valid_doc = {
        "id": f"{mock_date_str}_R1C1",
        "rc": "R1C1",
        "tickets_analysis": {"gpi_decision": "Play", "tickets": [{"type": "SP", "horses": ["1"]}]}
    }
    malformed_doc = {
        "id": f"{mock_date_str}_R1C2",
        "rc": "R1C2",
        "some_other_field": {} # Missing 'tickets_analysis'
    }

    mocker.patch("hippique_orchestrator.firestore_client.get_races_by_date_prefix", return_value=[valid_doc, malformed_doc])

    response = client.get(f"/pronostics?date={mock_date_str}")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 1 # Only the valid doc is processed
    assert len(data["pronostics"]) == 1
    assert data["pronostics"][0]["rc"] == "R1C1"


def test_api_pronostics_aggregates_multiple_docs(client, mocker):
    """
    Tests that the /pronostics endpoint correctly aggregates multiple valid
    documents from Firestore for the same date.
    """
    mock_date_str = "2025-12-07"

    doc1 = {"id": f"{mock_date_str}_R1C1", "rc": "R1C1", "tickets_analysis": {"gpi_decision": "Play", "tickets": [{"type": "SP", "horses": ["1"]}]}}
    doc2 = {"id": f"{mock_date_str}_R1C2", "rc": "R1C2", "tickets_analysis": {"gpi_decision": "Abstain", "tickets": [{"type": "TRIO", "horses": ["1", "2", "3"]}]}}

    mocker.patch("hippique_orchestrator.firestore_client.get_races_by_date_prefix", return_value=[doc1, doc2])

    response = client.get(f"/pronostics?date={mock_date_str}")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["total_races"] == 2
    assert len(data["pronostics"]) == 2
    assert data["pronostics"][0]["rc"] == "R1C1"
    assert data["pronostics"][1]["rc"] == "R1C2"


def test_api_pronostics_invalid_date_format(client):
    """
    Tests that the /pronostics endpoint returns a 422 error for an invalid
    date format.
    """
    response = client.get("/pronostics?date=not-a-date")
    assert response.status_code == 422
    assert "invalid date format" in response.json()["detail"].lower()

@pytest.mark.asyncio
async def test_tasks_bootstrap_day(client, mocker):
    mocker.patch("hippique_orchestrator.plan.build_plan_async", return_value=[
        {"date": "2025-11-24", "r_label": "R1", "c_label": "C1", "time_local": "12:00", "course_url": "http://example.com/c1"}
    ])
    mocker.patch("hippique_orchestrator.scheduler.schedule_all_races", return_value=[
        {"race": "R1C1", "phase": "H30", "ok": True, "task_name": "task-r1c1-h30"},
        {"race": "R1C1", "phase": "H5", "ok": True, "task_name": "task-r1c1-h5"},
    ])

    response = client.post("/tasks/bootstrap-day", json={"date": "2025-11-24", "mode": "tasks"})
    assert response.status_code == 202
    assert response.json()["ok"] is True
    assert "initiated in background" in response.json()["message"]

@pytest.mark.asyncio
async def test_tasks_run_phase(client, mocker):
    mocker.patch("hippique_orchestrator.runner.run_course", return_value={"ok": True, "phase": "H30", "artifacts": ["path/to/artifact"]})

    payload = {
                    "course_url": "http://example.com/r1c1-course",        "phase": "H30",
        "date": "2025-11-24",
        "trace_id": "test-trace-id"
    }
    response = client.post("/tasks/run-phase", json=payload)
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["phase"] == "H30"
    assert "artifacts" in response.json()
