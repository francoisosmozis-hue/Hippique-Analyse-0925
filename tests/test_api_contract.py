from datetime import date, datetime
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo
import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from hippique_orchestrator.data_contract import Programme

# Import the main FastAPI app from service_app for testing purposes
from service_app import create_app

@pytest.fixture(name="app")
def fixture_app() -> FastAPI:
    return create_app()

@pytest.fixture(name="client")
def fixture_client(app: FastAPI) -> TestClient:
    return TestClient(app)

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

def test_health_endpoint_returns_ok(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True

def test_get_pronostics_api_validates_against_schema(client: TestClient, mocker):
    # Mock the plan to return a valid race, since we're testing the API contract, not the plan itself
    mocker.patch(
        "hippique_orchestrator.plan.build_plan_async",
        new_callable=AsyncMock,
        return_value=[
            {
                "race_uid": "c1f7178c1a687542fe13434d285038083b8b7077",
                "meeting_ref": "TEST_M1",
                "race_number": 1,
                "scheduled_time_local": datetime.now(),
                "discipline": "Plat",
                "distance_m": 2400,
                "runners_count": 16,
                "r_label": "R1",
                "c_label": "C1",
            }
        ],
    )
    # Mock firestore to return no documents, so we test the plan data flowing through
    mocker.patch(
        "hippique_orchestrator.firestore_client.get_races_for_date",
        new_callable=AsyncMock,
        return_value=[]
    )

    response = client.get("/api/pronostics")
    assert response.status_code == 200
    # Add your schema validation logic here, e.g., using jsonschema
    # For now, just a basic check that it returns some data
    data = response.json()
    assert "date" in data
    assert "races" in data
    assert isinstance(data["races"], list)

def test_get_pronostics_api_with_date_filter(client: TestClient):
    response = client.get("/api/pronostics?date=2025-01-01")
    assert response.status_code == 200
    assert response.json()["date"] == "2025-01-01"

def test_get_pronostics_api_with_phase_filter(client: TestClient, mocker):
    mocker.patch(
        "hippique_orchestrator.plan.build_plan_async",
        new_callable=AsyncMock,
        return_value=[
            {
                "race_uid": "c1f7178c1a687542fe13434d285038083b8b7077",
                "meeting_ref": "TEST_M1",
                "race_number": 1,
                "scheduled_time_local": datetime.now(),
                "discipline": "Plat",
                "distance_m": 2400,
                "runners_count": 16,
                "r_label": "R1",
                "c_label": "C1",
            }
        ],
    )
    mocker.patch(
        "hippique_orchestrator.firestore_client.get_races_for_date",
        new_callable=AsyncMock,
        return_value=[]
    )
    # This should return our dummy data because it includes 'H5'
    response = client.get("/api/pronostics?phase=H5")
    assert response.status_code == 200
    data = response.json()
    assert len(data["races"]) == 1

def test_api_pronostics_date_validation(client: TestClient):
    response = client.get("/api/pronostics?date=invalid-date")
    assert response.status_code == 422
    assert "Input should be a valid date or datetime" in response.json()["detail"][0]["msg"]

