import pytest
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, patch

from hippique_orchestrator.data_contract import Programme

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

def test_get_pronostics_data_invalid_date(client: TestClient):
    """
    Tests that the /api/pronostics endpoint returns a 422 error
    for an invalid date format.
    """
    response = client.get("/api/pronostics?date=invalid-date")
    assert response.status_code == 422
    assert "Input should be a valid date or datetime" in response.json()["detail"][0]["msg"]

def test_get_pronostics_data_plan_only(client: TestClient, mocker):
    """
    Tests the /api/pronostics endpoint when there are races in the plan
    but no data in Firestore.
    """
    mocker.patch("hippique_orchestrator.firestore_client.get_races_for_date", return_value=[])
    mocker.patch(
        "hippique_orchestrator.programme_provider.get_programme_for_date",
        return_value=Programme(
            races=[
                {
                    "r_label": "R1",
                    "c_label": "C1",
                    "name": "PRIX DE TEST",
                    "time_local": "13:50",
                }
            ]
        ),
    )

    response = client.get("/api/pronostics?date=2025-01-01")
    assert response.status_code == 200
    data = response.json()
    assert len(data["races"]) == 1
    assert data["races"][0]["name"] == "PRIX DE TEST"
    assert "gpi_decision" not in data["races"][0]
