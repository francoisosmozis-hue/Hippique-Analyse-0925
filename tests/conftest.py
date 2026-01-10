"""
conftest.py - Global test configuration and fixtures for pytest.
"""

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Import the app and the config module to be mocked
from hippique_orchestrator.service import app


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


@pytest.fixture(scope="session")
def client():
    """
    Test client for the FastAPI app. It's function-scoped to ensure
    that mocks applied in one test don't leak into others.
    Uses a 'with' statement for proper client shutdown.
    """
    with TestClient(app) as client_instance:
        yield client_instance


@pytest.fixture
def disable_auth(mocker):
    """Fixture to disable authentication for specific tests."""
    from hippique_orchestrator.auth import check_api_key  # noqa: PLC0415

    # Define an empty override function
    async def override_check_api_key():
        return

    # Override the dependency for the duration of the test
    app.dependency_overrides[check_api_key] = override_check_api_key
    yield
    # Clean up the override after the test is done
    app.dependency_overrides.clear()
