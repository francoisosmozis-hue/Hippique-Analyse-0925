from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from hippique_orchestrator.service import app

client = TestClient(app)


def test_health_check_returns_ok():
    """
    Test the /health endpoint to ensure it returns a 200 OK response.
    """
    response = client.get("/health")
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "healthy"
    assert "version" in json_response


def test_debug_config_returns_ok_and_has_expected_keys():
    """
    Test the /debug/config endpoint to ensure it returns a 200 OK response
    and contains the expected configuration keys.
    """
    response = client.get("/debug/config")
    assert response.status_code == 200
    json_response = response.json()

    # Check for the presence of key configuration fields
    expected_keys = [
        "require_auth",
        "internal_api_secret_is_set",
        "project_id",
        "bucket_name",
        "task_queue",
        "log_level",
        "timezone",
        "version",
    ]
    for key in expected_keys:
        assert key in json_response


@patch("hippique_orchestrator.service.plan.build_plan_async", new_callable=AsyncMock)
@patch("hippique_orchestrator.service.firestore_client.get_races_for_date")
def test_get_pronostics_api_with_mocked_data(mock_get_races, mock_build_plan):
    """
    Tests the /api/pronostics endpoint with mocked data sources to verify
    data merging and processing logic.
    """
    # 1. Setup Mock Data
    test_date = "2023-01-20"

    # Mock for plan.build_plan_async
    mock_build_plan.return_value = [
        {"r_label": "R1", "c_label": "C1", "name": "Prix de Test"},
        {"r_label": "R1", "c_label": "C2", "name": "Prix Inconnu"},
    ]

    # Mocks for firestore_client.get_races_for_date
    mock_race_doc = MagicMock()
    mock_race_doc.id = f"{test_date}_R1C1"
    mock_race_doc.to_dict.return_value = {
        "rc": "R1C1",
        "tickets_analysis": {"gpi_decision": "play_safe"},
        "last_analyzed_at": "2023-01-20T10:00:00Z",
    }
    mock_get_races.return_value = [mock_race_doc]

    # 2. Action
    response = client.get(f"/api/pronostics?date={test_date}")

    # 3. Assertions
    assert response.status_code == 200
    mock_build_plan.assert_called_once_with(test_date)
    mock_get_races.assert_called_once_with(test_date)

    data = response.json()
    assert data["ok"] is True
    assert data["date"] == test_date
    assert data["counts"]["total_in_plan"] == 2
    assert data["counts"]["total_processed"] == 1
    assert data["counts"]["total_playable"] == 1
    assert data["counts"]["total_pending"] == 1  # (total_in_plan - total_processed)

    races = data["races"]
    assert len(races) == 2

    # Find the processed race and the pending race
    processed_race = next((p for p in races if p["rc"] == "R1C1"), None)
    pending_race = next((p for p in races if p["rc"] == "R1C2"), None)

    assert processed_race is not None
    assert processed_race["status"] == "playable"
    assert processed_race["tickets_analysis"]["gpi_decision"] == "play_safe"

    assert pending_race is not None
    assert pending_race["status"] == "pending"
    assert pending_race["gpi_decision"] is None
