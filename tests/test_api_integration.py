from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, time

import pytest
from fastapi.testclient import TestClient

from hippique_orchestrator.data_contract import Programme, Race

class MockDocumentSnapshot:
    def __init__(self, doc_id: str, data: dict):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data

@pytest.fixture
def mock_race_doc():
    """Fixture to create a mock Firestore DocumentSnapshot."""
    def _mock_race_doc(doc_id: str, data: dict):
        return MockDocumentSnapshot(doc_id, data)
    return _mock_race_doc

# This is a temporary patch for Programme.model_validate. The mock for this
# needs to provide valid data for the Race.hippodrome, because the Race model
# has been updated to make hippodrome optional, but the current test data
# structure doesn't reflect this.
# TODO: Refactor test data / mocks to properly handle the optional hippodrome field.
@pytest.fixture(autouse=True)
def patch_programme_model_validate(mocker):
    """
    This is a temporary patch for Programme.model_validate. The mock for this
    needs to provide valid data for the Race.hippodrome, because the Race model
    has been updated to make hippodrome optional, but the current test data
    structure doesn't reflect this.
    TODO: Refactor test data / mocks to properly handle the optional hippodrome field.
    """
    original_model_validate = Programme.model_validate
    def mocked_model_validate(data):
        # Ensure that if hippodrome is missing, it's set to None explicitly
        for race in data.get("races", []):
            if "hippodrome" not in race:
                race["hippodrome"] = None
        return original_model_validate(data)

    mocker.patch('hippique_orchestrator.data_contract.Programme.model_validate', side_effect=mocked_model_validate)

def test_health_check_returns_ok(client: TestClient):
    """
    Test the /health endpoint to ensure it returns a 200 OK response.
    """
    # This is a test
    response = client.get("/health")
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["ok"] is True


def test_debug_config_returns_ok_and_has_expected_keys(client: TestClient):
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
        "gcs_bucket_name",
        "cloud_tasks_queue",
        "environment",
        "version",
    ]
    for key in expected_keys:
        assert key in json_response

@patch("hippique_orchestrator.service.firestore_client.get_races_for_date")
@patch("hippique_orchestrator.service.get_programme_for_date")
def test_get_pronostics_api_with_mocked_data(mock_get_programme_for_date, mock_get_races, client: TestClient):
    """
    Tests the /api/pronostics endpoint with mocked data sources to verify
    data merging and processing logic.
    """
    # 1. Setup Mock Data
    test_date = "2023-01-20"
    test_date_obj = date(2023, 1, 20)

    # Mock for programme_provider.get_programme_for_date
    mock_programme_data = {
        "date": test_date_obj,
        "races": [
                            {
                                "race_id": "C1",
                                "reunion_id": 1,
                                "course_id": 1,
                                "hippodrome": "VINCENNES",
                                "date": test_date_obj,
                                "start_time": time(13, 50),
                                "name": "Prix de Test",
                                "discipline": "Trot Attelé",
                                "country_code": "FR",
                                "url": "http://example.com/r1c1",
                                "rc": "R1C1",
                            },
                            {
                                "race_id": "C2",
                                "reunion_id": 1,
                                "course_id": 2,
                                "hippodrome": "VINCENNES",
                                "date": test_date_obj,
                                "start_time": time(14, 20),
                                "name": "Prix Inconnu",
                                "discipline": "Plat",
                                "country_code": "FR",
                                "url": "http://example.com/r1c2",
                                "rc": "R1C2",
                            },        ],
    }
    mock_get_programme_for_date.return_value = Programme.model_validate(mock_programme_data)

    # Mocks for firestore_client.get_races_for_date
    mock_race_doc = MagicMock()
    mock_race_doc.id = f"{test_date}_R1C1"
    mock_race_doc.to_dict.return_value = {
        "rc": "R1C1",
        "r_label": "R1",
        "c_label": "C1",
        "gpi_decision": "play_safe",
        "last_analyzed_at": "2023-01-20T10:00:00Z",
    }
    mock_get_races.return_value = [mock_race_doc]

    # 2. Action
    response = client.get(f"/api/pronostics?date={test_date}")

    # 3. Assertions
    assert response.status_code == 200
    mock_get_programme_for_date.assert_called_once_with(test_date_obj)
    mock_get_races.assert_called_once_with(test_date_obj)
    data = response.json()
    assert "date" in data
    assert "races" in data
    assert isinstance(data["races"], list)
    assert len(data["races"]) == 2

    # Find the processed race and the pending race
    processed_race = next((p for p in data["races"] if p["race_id"] == "C1"), None)
    pending_race = next((p for p in data["races"] if p["race_id"] == "C2"), None)

    assert processed_race is not None
    assert processed_race["gpi_decision"] == "play_safe"

    assert pending_race is not None
    assert "gpi_decision" not in pending_race
