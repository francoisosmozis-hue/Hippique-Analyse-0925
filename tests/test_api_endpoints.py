from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import re

import pytest
from bs4 import BeautifulSoup


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
    """Tests that the API validates the date format."""
    response = client.get("/api/pronostics?date=not-a-real-date")
    assert response.status_code == 422
    assert "Invalid date format" in response.json()["detail"]


def test_api_pronostics_default_date_is_today(client, mocker, mock_firestore_client):
    """Tests that the API uses today's date by default."""
    mock_firestore_client.return_value = []

    # Mock datetime.now to control "today's" date
    mock_today = datetime(2025, 7, 15, tzinfo=ZoneInfo("Europe/Paris"))
    mocker.patch(
        "hippique_orchestrator.service.datetime", MagicMock(now=MagicMock(return_value=mock_today))
    )

    response = client.get("/api/pronostics")
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
    assert data["pronostics"] == []


def test_api_pronostics_etag_304_not_modified(client, mock_firestore_client, mocker):
    """Tests that the server returns a 304 if the ETag matches."""
    mock_firestore_client.return_value = []

    # Mock datetime.now to ensure the server_timestamp is stable
    mock_now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=ZoneInfo("UTC"))
    mocker.patch(
        "hippique_orchestrator.service.datetime", MagicMock(now=MagicMock(return_value=mock_now))
    )

    # First request to get an ETag
    response1 = client.get("/api/pronostics?date=2025-01-01")
    assert response1.status_code == 200
    etag = response1.headers.get("etag")
    assert etag is not None

    # Second request with the same ETag
    headers = {"If-None-Match": etag}
    response2 = client.get("/api/pronostics?date=2025-01-01", headers=headers)
    assert response2.status_code == 304


def test_api_pronostics_rich_response_structure(client, mocker):
    """
    Tests that the API returns the new, rich JSON structure with correct status aggregation.
    Also validates the basic structure of the JSON response.
    """
    now_iso = datetime.now(ZoneInfo("UTC")).isoformat()
    docs = [
        MockDocumentSnapshot(
            "2025-01-01_R1C1",
            {
                "r_label": "R1",
                "c_label": "C1",
                "rc": "R1C1",
                "reunion": "R1",  # Added for consistency
                "num": "C1",  # Added for consistency
                "nom": "Course 1",  # Added for consistency
                "last_analyzed_at": now_iso,
                "tickets_analysis": {"gpi_decision": "Play"},
            },
        ),
        MockDocumentSnapshot(
            "2025-01-01_R1C2",
            {
                "r_label": "R1",
                "c_label": "C2",
                "rc": "R1C2",
                "reunion": "R1",  # Added for consistency
                "num": "C2",  # Added for consistency
                "nom": "Course 2",  # Added for consistency
                "last_analyzed_at": now_iso,
                "tickets_analysis": {"gpi_decision": "Abstain"},
            },
        ),
        MockDocumentSnapshot(
            "2025-01-01_R1C3",
            {
                "r_label": "R1",
                "c_label": "C3",
                "rc": "R1C3",
                "reunion": "R1",  # Added for consistency
                "num": "C3",  # Added for consistency
                "nom": "Course 3",  # Added for consistency
                "last_analyzed_at": now_iso,
                "tickets_analysis": {"gpi_decision": "ERROR"},
            },
        ),
    ]
    # We have 3 docs in DB, but let's say the plan has 4 races.
    plan_races = [
        {"r_label": "R1", "c_label": "C1"},
        {"r_label": "R1", "c_label": "C2"},
        {"r_label": "R1", "c_label": "C3"},
        {"r_label": "R1", "c_label": "C4"},
    ]
    mocker.patch("hippique_orchestrator.plan.build_plan_async", return_value=plan_races)
    mocker.patch("hippique_orchestrator.firestore_client.get_races_for_date", return_value=docs)

    response = client.get("/api/pronostics?date=2025-01-01")
    assert response.status_code == 200
    data = response.json()

    # Basic structural validation
    assert isinstance(data, dict)
    assert "ok" in data and isinstance(data["ok"], bool)
    assert "date" in data and isinstance(data["date"], str)
    assert "source" in data and isinstance(data["source"], str)
    assert "reason_if_empty" in data  # Can be None
    assert "status_message" in data and isinstance(data["status_message"], str)
    assert "last_updated" in data and isinstance(data["last_updated"], str)
    assert "counts" in data and isinstance(data["counts"], dict)
    assert "pronostics" in data and isinstance(data["pronostics"], list)

    # Validate each pronostic item structure
    for pronostic in data["pronostics"]:
        assert isinstance(pronostic, dict)
        assert "rc" in pronostic and isinstance(pronostic["rc"], str)
        assert "status" in pronostic and isinstance(pronostic["status"], str)
        # Check for 'reunion' and 'num' as they are always present for fetched/pending races.
        assert "reunion" in pronostic  # Can be None for processed races without it
        assert "num" in pronostic  # Can be None for processed races without it
        # No direct assert for "gpi_decision", "details_url", "analysis_summary" as they vary

    # Use a set for keys that might not be in the exact order in some Python versions
    expected_counts_keys = {
        "total_in_plan",
        "total_processed",
        "total_analyzed",
        "total_playable",
        "total_abstain",
        "total_error",
        "total_pending",
    }
    assert set(data["counts"].keys()) == expected_counts_keys

    assert data["counts"]["total_in_plan"] == 4
    assert data["counts"]["total_processed"] == 3
    assert data["counts"]["total_analyzed"] == 3
    assert data["counts"]["total_playable"] == 1
    assert data["counts"]["total_abstain"] == 1
    assert data["counts"]["total_error"] == 1
    assert data["counts"]["total_pending"] == 1

    pronostics = {p.get("rc"): p for p in data["pronostics"]}
    assert pronostics["R1C1"]["status"] == "playable"
    assert pronostics["R1C2"]["status"] == "abstain"
    assert pronostics["R1C3"]["status"] == "error"
    assert pronostics["R1C4"]["status"] == "pending"
