import httpx
import pytest
from bs4 import BeautifulSoup
from freezegun import freeze_time
from httpx import ASGITransport


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


@pytest.fixture
def mock_firestore_client(mocker):
    """Mocks the Firestore client to return predictable data."""
    # Mock the main function that the service uses
    return mocker.patch("hippique_orchestrator.firestore_client.get_races_for_date")


def test_health_check_endpoint(client):
    """Tests the /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_pronostics_ui_endpoint(client):
    """Tests that /pronostics returns the main HTML page and checks for specific content."""
    response = client.get("/pronostics")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Hippique Orchestrator - Pronostics" in response.text  # Check title tag

    # Further checks for specific HTML structure
    soup = BeautifulSoup(response.text, "html.parser")

    # Check for the main layout elements
    assert soup.find("header") is not None, "Should find a header tag"
    assert soup.find("h1", string="Pronostics Hippiques") is not None, (
        "Should find the main H1 title"
    )
    assert soup.find("main") is not None, "Should find a main tag"

    # Check for core sections and their IDs
    assert soup.find("div", id="error-container") is not None, "Should find the error container"
    assert soup.find("section", id="controls-section") is not None, (
        "Should find the controls section"
    )
    assert soup.find("input", id="date-picker") is not None, "Should find the date picker input"
    assert soup.find("section", id="stats-section") is not None, "Should find the stats section"
    assert soup.find("strong", id="api-status-message") is not None, (
        "Should find the API status message"
    )
    assert soup.find("section", id="races-section") is not None, "Should find the races section"
    assert soup.find("table", id="races-table") is not None, "Should find the races table"
    assert soup.find("tbody", id="races-tbody") is not None, "Should find the races table body"

    # Check for a script tag that references the API endpoint
    all_script_text = ""
    for script_tag in soup.find_all("script"):
        if script_tag.string:
            all_script_text += script_tag.string
        elif script_tag.text:
            all_script_text += script_tag.text

    assert all_script_text, "Should have captured script text"
    assert "document.addEventListener('DOMContentLoaded'" in all_script_text, (
        "Should find core JS functionality"
    )
    assert "/api/pronostics" in all_script_text, (
        "Should find reference to /api/pronostics endpoint in JS/scripts"
    )


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
async def test_api_pronostics_default_date_is_today(app, mock_firestore_client, mock_build_plan):
    """Tests that the API defaults to today's date when none is provided."""
    mock_firestore_client.return_value = []
    mock_build_plan.return_value = []

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/pronostics")

    assert response.status_code == 200
    assert response.json()["date"] == "2025-07-15"


def test_api_pronostics_empty_response(client, mock_firestore_client):
    """Tests the API response when no races are found."""
    mock_firestore_client.return_value = []
    response = client.get("/api/pronostics?date=2025-01-01")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["date"] == "2025-01-01"
    assert data["counts"]["total_in_plan"] == 0
    assert data["races"] == []


@pytest.mark.asyncio
@freeze_time("2025-01-01")
async def test_api_pronostics_etag_304_not_modified(app, mock_firestore_client, mock_build_plan):
    """Tests that the API returns a 304 Not Modified when the ETag matches."""
    mock_firestore_client.return_value = []
    mock_build_plan.return_value = []

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
    app, mock_firestore_client, mock_build_plan, mock_race_doc
):
    """Tests the structure of the API response when data is present."""
    mock_firestore_client.return_value = [
        mock_race_doc("2025-01-01_R1C1", {"gpi_decision": "play"}),
        mock_race_doc("2025-01-01_R1C2", {"gpi_decision": "abstain"}),
    ]
    mock_build_plan.return_value = [
        {
            "date": "2025-01-01",
            "r_label": "R1",
            "c_label": "C1",
            "time_local": "13:50",
            "course_url": "http://example.com/r1c1",
        },
        {
            "date": "2025-01-01",
            "r_label": "R1",
            "c_label": "C2",
            "time_local": "14:20",
            "course_url": "http://example.com/r1c2",
        },
    ]
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/pronostics?date=2025-01-01")

    assert response.status_code == 200
    data = response.json()
    assert "generated_at" in data
    assert "day_id" in data
    assert data["day_id"] == "2025-01-01"
    assert "races" in data
    assert len(data["races"]) == 2
    assert data["races"][0]["r_label"] == "R1"
    assert data["races"][0]["c_label"] == "C1"
    assert data["races"][0]["gpi_decision"] == "play"
    assert data["races"][1]["gpi_decision"] == "abstain"

