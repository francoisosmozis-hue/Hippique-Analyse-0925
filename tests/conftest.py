"""
conftest.py - Global test configuration and fixtures for pytest.
"""

import pytest
from pathlib import Path
import subprocess
from unittest.mock import MagicMock

# Import the Config class
from hippique_orchestrator.config import Config

@pytest.fixture(scope="session", autouse=True)
def mock_network_calls(session_mocker):
    """
    Session-scoped fixture to automatically mock all network calls made with `requests.get`.
    This prevents any real HTTP requests during the entire test session, making tests
    fast and reliable.
    """
    # Read default HTML content to be returned by the mock
    # This can be overridden in specific tests if needed.
    try:
        html_content = (Path(__file__).parent / "fixtures" / "boturfers_programme.html").read_bytes()
    except FileNotFoundError:
        # Provide a fallback if the fixture file is missing
        html_content = b"<html><head><title>Default Mock</title></head><body></body></html>"

    # Create a mock response object that simulates a real requests.Response
    mock_response = session_mocker.Mock()
    mock_response.content = html_content
    mock_response.raise_for_status.return_value = None # Mock the method to do nothing

    # Patch requests.get in the modules where it's used.
    # It's important to patch where the object is looked up.
    session_mocker.patch("hippique_orchestrator.scrapers.boturfers.requests.get", return_value=mock_response)
    session_mocker.patch("hippique_orchestrator.stats_fetcher.requests.get", return_value=mock_response)
    # Patch requests.get for httpx as well if used directly (e.g., in geny scraper)
    session_mocker.patch("httpx.get", return_value=session_mocker.Mock(status_code=200, text=str(html_content)))


@pytest.fixture(scope="session", autouse=True)
def mock_subprocess_run(session_mocker):
    """
    Session-scoped fixture to automatically mock all calls to `subprocess.run`.
    This prevents tests from executing external scripts, which can be slow and
    have unintended side effects.
    """
    mock_process = session_mocker.Mock(spec=subprocess.CompletedProcess)
    mock_process.returncode = 0
    mock_process.stdout = ""
    mock_process.stderr = ""

    # Patch subprocess.run globally for the test session.
    # Any module that imports `subprocess` will get this mock.
    session_mocker.patch("subprocess.run", return_value=mock_process)


@pytest.fixture(scope="function") # Use function scope to ensure a fresh config for each test
def mock_config(mocker):
    """
    Fixture to mock the get_config function and provide a test-specific Config object.
    """
    mock_config_instance = Config(
        PROJECT_ID="test-project",
        REGION="europe-west1",
        SERVICE_NAME="test-service",
        QUEUE_ID="test-queue",
        GCS_BUCKET="test-bucket",
        REQUIRE_AUTH=False, # Auth disabled for tests
        TZ="Europe/Paris",
        BUDGET_TOTAL=5.0,
        EV_MIN_GLOBAL=0.40,
        ROI_MIN_GLOBAL=0.25,
        EV_MIN_SP=0.15,
        MAX_COMBO_OVERROUND=1.30,
    )
    mocker.patch("hippique_orchestrator.config.get_config", return_value=mock_config_instance)
    return mock_config_instance

# Fixture for TestClient setup, ensuring it uses the mocked config
@pytest.fixture(scope="module")
def client(mock_config): # Pass mock_config here
    """
    Test client for the FastAPI app, using a mocked configuration.
    """
    from hippique_orchestrator.service import app
    from fastapi.testclient import TestClient
    return TestClient(app)