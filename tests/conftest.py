"""
conftest.py - Global test configuration and fixtures for pytest.
"""

from datetime import datetime, date
from typing import List, Dict, Any

from hippique_orchestrator.data_contract import Programme, Race
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

# Import the app and the config module to be mocked
from hippique_orchestrator.service import app as fastapi_app


@pytest.fixture(scope="session")
def mock_network_calls(session_mocker):
    """
    Session-scoped fixture to automatically mock all network calls.
    This prevents any real HTTP requests during the entire test session.
    """
    try:
        # This will be the default response for all httpx GET requests
        html_content = (Path(__file__).parent.parent / "boturfers_programme.html").read_bytes()
    except FileNotFoundError:
        html_content = b"<html><body>Default Mock Content</body></html>"

    # --- Mock for 'httpx' library (robust version) ---
    mock_httpx_response = session_mocker.Mock()
    mock_httpx_response.status_code = 200
    mock_httpx_response.content = html_content
    mock_httpx_response.text = html_content.decode('utf-8')
    mock_httpx_response.raise_for_status.return_value = None

    # This correctly mocks the async context manager
    mock_async_client = session_mocker.MagicMock()
    mock_async_client.__aenter__.return_value = mock_async_client  # Return self for async with
    mock_async_client.__aexit__.return_value = False  # Explicitly mock async exit
    mock_async_client.get.return_value = mock_httpx_response
    session_mocker.patch("httpx.AsyncClient", return_value=mock_async_client)

    # --- Legacy mock for 'requests' library ---
    mock_requests_response = session_mocker.Mock()
    mock_requests_response.content = html_content
    mock_requests_response.raise_for_status.return_value = None
    session_mocker.patch(
        "hippique_orchestrator.scrapers.boturfers.requests.get",
        return_value=mock_requests_response,
        create=True,
    )


@pytest.fixture(scope="session")
def mock_subprocess_run(session_mocker):
    """
    Session-scoped fixture to automatically mock all calls to `subprocess.run`.
    """
    mock_process = session_mocker.Mock(spec=subprocess.CompletedProcess)
    mock_process.returncode = 0
    mock_process.stdout = ""
    mock_process.stderr = ""
    session_mocker.patch("subprocess.run", return_value=mock_process)


@pytest.fixture(autouse=True)
def mock_config_values(mocker):
    """
    Automatically mocks all necessary configuration variables for each test function.
    This ensures test isolation and predictable behavior without hitting real services.
    """
    mocker.patch("hippique_orchestrator.config.PROJECT_ID", "test-project")
    mocker.patch("hippique_orchestrator.config.LOCATION", "europe-west1")
    mocker.patch("hippique_orchestrator.config.BUCKET_NAME", "test-bucket")
    mocker.patch("hippique_orchestrator.config.TASK_QUEUE", "test-queue")
    mocker.patch("hippique_orchestrator.config.TASK_OIDC_SA_EMAIL", "test-sa@example.com")
    mocker.patch("hippique_orchestrator.config.REQUIRE_AUTH", False)  # Disable auth for most tests
    mocker.patch("hippique_orchestrator.config.FIRESTORE_COLLECTION", "races-test")
    mocker.patch("hippique_orchestrator.config.INTERNAL_API_SECRET", "test-secret")

    # Mock the firestore client at the source to prevent real connections during import
    mocker.patch("google.cloud.firestore.Client", return_value=mocker.MagicMock())


@pytest.fixture(scope="function")
def client(mocker):
    """
    Test client for the FastAPI app. It's function-scoped to ensure
    that mocks applied in one test don't leak into others.

    This fixture also applies a default mock for the plan builder to prevent
    widespread test failures when the API is called.
    """
    # Default mock for the plan builder to return one valid race
    mock_plan_data = [
        {
            "race_uid": "TEST_R1C1_UID",
            "meeting_ref": "TEST_M1",
            "race_number": 1,
            "scheduled_time_local": datetime.now(),
            "discipline": "Plat",
            "distance_m": 2400,
            "runners_count": 16,
            "status": "SCHEDULED",
            "course_url": "http://example.com/r1c1",
            "r_label": "R1",
            "c_label": "C1",
        }
    ]
    mocker.patch(
        "hippique_orchestrator.service.plan.build_plan_async",
        new_callable=AsyncMock,
        return_value=mock_plan_data,
    )

    with TestClient(fastapi_app) as client_instance:
        yield client_instance


@pytest.fixture
def disable_auth(mocker):
    """Fixture to disable authentication for specific tests."""
    from hippique_orchestrator.auth import check_api_key  # noqa: PLC0415

    # Define an empty override function
    async def override_check_api_key():
        return

    # Override the dependency for the duration of the test
    fastapi_app.dependency_overrides[check_api_key] = override_check_api_key
    yield
    # Clean up the override after the test is done
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def mock_build_plan(mocker):
    """Mocks plan.build_plan_async."""
    mock_plan = mocker.patch(
        "hippique_orchestrator.plan.build_plan_async", new_callable=AsyncMock
    )
    # Define a mock Programme data structure conforming to the Pydantic model
    mock_programme_data = {
        "date": date(2025, 1, 1),
        "races": [
            {
                "race_id": "C1",
                "reunion_id": 1,
                "course_id": 1,
                "hippodrome": "Mockdrome",
                "date": date(2025, 1, 1),
                "name": "Prix Gemini",
                "discipline": "Trot Attelé",
                "url": "http://mock.url/R1C1",
                "runners": [
                    {"num": 1, "nom": "Mock Horse A", "odds_win": 2.5, "odds_place": 1.2},
                    {"num": 2, "nom": "Mock Horse B", "odds_win": 5.0, "odds_place": 1.5},
                ],
            },
            {
                "race_id": "C2",
                "reunion_id": 1,
                "course_id": 2,
                "hippodrome": "Mockdrome",
                "date": date(2025, 1, 1),
                "name": "Prix Agent",
                "discipline": "Plat",
                "url": "http://mock.url/R1C2",
                "runners": [
                    {"num": 1, "nom": "Mock Horse C", "odds_win": 3.0, "odds_place": 1.3},
                    {"num": 2, "nom": "Mock Horse D", "odds_win": 6.0, "odds_place": 1.6},
                ],
            },
        ],
    }
    mock_plan.return_value = Programme.model_validate(mock_programme_data) # Return validated Programme object
    return mock_plan


@pytest.fixture
def mock_race_doc(mocker):
    """Helper to create mock Firestore race documents."""

    def _mock_race_doc(doc_id, data):
        mock_doc = mocker.MagicMock()
        mock_doc.id = doc_id
        mock_doc.to_dict.return_value = data
        return mock_doc

    return _mock_race_doc


@pytest.fixture
def app():
    """ASGI app fixture for httpx.ASGITransport tests."""
    return fastapi_app


@pytest.fixture
def mock_firestore(mocker):
    """
    Fixture attendue par tests/test_service.py: (mock_get_races, mock_get_status).
    Patch le symbole dans firestore_client ET dans service.firestore_client (robuste aux imports).
    """
    mock_get_races = AsyncMock(return_value=[])
    mock_get_status = AsyncMock(return_value={
        "processed": 0,
        "pending": 0,
        "errors": 0,
        "total_races": 0,
        "reason": "No races",
    })

    # Patch module source
    mocker.patch("hippique_orchestrator.firestore_client.get_races_for_date", new=mock_get_races)
    mocker.patch("hippique_orchestrator.firestore_client.get_processing_status_for_date", new=mock_get_status)

    # Patch symbole réellement utilisé par le endpoint (importé dans service.py)
    mocker.patch("hippique_orchestrator.service.firestore_client.get_races_for_date", new=mock_get_races)
    mocker.patch("hippique_orchestrator.service.firestore_client.get_processing_status_for_date", new=mock_get_status)

    return (mock_get_races, mock_get_status)

@pytest.fixture
def mock_cloud_tasks(mocker):
    """
    Centralized mock for the Cloud Tasks client.
    Patches the client at the source and returns a mock instance.
    """
    mock_client_instance = mocker.MagicMock()
    mock_client_instance.create_task.return_value = mocker.MagicMock(
        name="projects/p/locations/l/queues/q/tasks/t"
    )

    # Patch the client where it is imported and used in the scheduler
    mocker.patch(
        "hippique_orchestrator.scheduler.tasks_v2.CloudTasksClient",
        return_value=mock_client_instance,
    )
    return mock_client_instance


@pytest.fixture
def race_document_factory(mocker):
    """
    Factory fixture to create consistent mock Firestore documents for race data.
    Ensures that essential keys like 'last_modified_at' are always present.
    """
    def _factory(doc_id: str, data: dict):
        mock_doc = mocker.MagicMock()
        mock_doc.id = doc_id

        # Ensure essential keys are present
        if 'last_modified_at' not in data:
            data['last_modified_at'] = datetime.now()

        mock_doc.to_dict.return_value = data
        mock_doc.exists = True
        return mock_doc

    return _factory

