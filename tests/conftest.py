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
    Session-scoped fixture to automatically mock all network calls made with `requests` and `httpx`.
    This prevents any real HTTP requests during the entire test session.
    """
    try:
        html_content = (
            Path(__file__).parent / "fixtures" / "boturfers_programme.html"
        ).read_bytes()
    except FileNotFoundError:
        html_content = b"<html><body>Default Mock</body></html>"

    # Mock for 'requests' library
    mock_requests_response = session_mocker.Mock()
    mock_requests_response.content = html_content
    mock_requests_response.raise_for_status.return_value = None
    session_mocker.patch(
        "hippique_orchestrator.scrapers.boturfers.requests.get", return_value=mock_requests_response
    )

    # Mock for 'httpx' library
    mock_httpx_response = session_mocker.Mock()
    mock_httpx_response.status_code = 200
    mock_httpx_response.content = html_content
    mock_httpx_response.text = html_content.decode()
    mock_httpx_response.raise_for_status.return_value = None

    # Mock the async client context manager
    async def mock_async_context_manager(*args, **kwargs):
        return mock_httpx_response

    mock_async_client = session_mocker.AsyncMock()
    mock_async_client.get = session_mocker.AsyncMock(return_value=mock_httpx_response)

    # Patch the AsyncClient context manager
    session_mocker.patch("httpx.AsyncClient", return_value=mock_async_client)


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
def client():
    """
    Test client for the FastAPI app. It's function-scoped to ensure
    that mocks applied in one test don't leak into others.
    """
    return TestClient(app)


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
