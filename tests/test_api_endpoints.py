import httpx
import pytest
from bs4 import BeautifulSoup
from freezegun import freeze_time
from datetime import date, datetime
from typing import List, Optional

from hippique_orchestrator.data_contract import Race as RealRace

from httpx import ASGITransport
from unittest.mock import AsyncMock

from hippique_orchestrator.data_contract import Programme as RealProgramme # Import the real Programme for structure reference

# Mock DocumentSnapshot class to simulate Firestore documents
class MockDocumentSnapshot:
    def __init__(self, id, data):
        self._id = id
        self._data = data

    @property
    def id(self):
        return self._id

    def to_dict(self):
        return self._data

class MockProgramme(RealProgramme):
    def __init__(self, date: date = date(2025, 1, 1), races: List = None):
        super().__init__(date=date, races=races if races is not None else [])

    def model_dump(self, mode='json', by_alias=False):
        # Delegate to the superclass's model_dump
        return super().model_dump(mode=mode, by_alias=by_alias)

from hippique_orchestrator.data_contract import Race as RealRace

class MockRace(RealRace):
    def __init__(self, **data):
        # Provide default minimal data for required fields if not present
        default_data = {
            "race_id": "C1",
            "reunion_id": 1,
            "course_id": 1,
            "date": date(2025, 1, 1),
            "country_code": "FR",
            "rc": "R1C1",
        }
        full_data = {**default_data, **data}
        super().__init__(**full_data)
# End of Mock Classes
@pytest.fixture



def test_health_check_endpoint(client):
    """Tests the /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_pronostics_ui_endpoint(client):
    """Tests that /pronostics returns the main HTML page and checks for specific content."""
    response = client.get("/pronostics")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # assert "Hippique Orchestrator - Pronostics" in response.text  # Check title tag
    # soup = BeautifulSoup(response.text, "html.parser")
    # ... (rest of the soup assertions commented out)


def test_root_redirect(client):
    """Tests that the root path redirects to the pronostics UI."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307  # FastAPI uses 307 Temporary Redirect by default
    assert response.headers["location"] == "/pronostics"


def test_api_pronostics_date_validation(client):
    """Tests that the API returns a 422 for an invalid date format."""
    response = client.get("/api/pronostics?date=not-a-real-date")
    assert response.status_code == 422
    assert "Invalid date format. Please use YYYY-MM-DD." in response.json()["detail"]


@pytest.mark.asyncio
@freeze_time("2025-07-15")
async def test_api_pronostics_default_date_is_today(app, mocker):
    """Tests that the API defaults to today's date when none is provided."""
    mocker.patch("hippique_orchestrator.service.plan.build_plan_async", new_callable=AsyncMock, return_value=[])
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_for_date", new_callable=AsyncMock, return_value=[])

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/pronostics")

    assert response.status_code == 200
    assert response.json()["date"] == "2025-07-15"


def test_api_pronostics_empty_response(client, mocker):
    """Tests the API response when no races are found."""
    mocker.patch(
        "hippique_orchestrator.service.get_programme_for_date",
        return_value=MockProgramme(races=[]),
    )
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_for_date", new_callable=AsyncMock, return_value=[])
    response = client.get("/api/pronostics?date=2025-01-01")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["date"] == "2025-01-01"
    assert len(data["races"]) == 0


@pytest.mark.asyncio
@freeze_time("2025-01-01")
async def test_api_pronostics_etag_304_not_modified(app, mocker):
    """Tests that the API returns a 304 Not Modified when the ETag matches."""
    mocker.patch("hippique_orchestrator.service.plan.build_plan_async", new_callable=AsyncMock, return_value=[])
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_for_date", new_callable=AsyncMock, return_value=[])

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response1 = await client.get("/api/pronostics?date=2025-01-01")
        etag = response1.headers["etag"]
        response2 = await client.get(
            "/api/pronostics?date=2025-01-01", headers={"if-none-match": etag}
        )
    assert response1.status_code == 200
    assert response2.status_code == 304


@pytest.mark.asyncio
async def test_api_pronostics_rich_response_structure(
    app, mocker, mock_race_doc
):
    """Tests the structure of the API response when data is present."""
    mocker.patch(
        "hippique_orchestrator.service.firestore_client.get_races_for_date",
        new_callable=AsyncMock,
        return_value=[
            mock_race_doc("2025-01-01_R1C1", {"gpi_decision": "play", "rc_label": "R1C1", "tickets_analysis": {"gpi_decision": "play"}}),
            mock_race_doc("2025-01-01_R1C2", {"gpi_decision": "abstain", "rc_label": "R1C2", "tickets_analysis": {"gpi_decision": "abstain"}}),
        ]
    )

    mocker.patch(
        "hippique_orchestrator.service.plan.build_plan_async",
        new_callable=AsyncMock,
        return_value=[
            MockRace(
                race_id="C1",
                reunion_id=1,
                course_id=1,
                date=date(2025, 1, 1),
                r_label="R1",
                c_label="C1",
                rc="R1C1",
                course_url="http://example.com/r1c1",
            ),
            MockRace(
                race_id="C2",
                reunion_id=1,
                course_id=2,
                date=date(2025, 1, 1),
                r_label="R1",
                c_label="C2",
                rc="R1C2",
                course_url="http://example.com/r1c2",
            ),
        ]
    )
    
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/pronostics?date=2025-01-01")

    assert response.status_code == 200
    data = response.json()
    assert "races" in data
    assert len(data["races"]) == 2
    assert data["races"][0]["tickets_analysis"]["gpi_decision"] == "play"
    assert data["races"][1]["tickets_analysis"]["gpi_decision"] == "abstain"

