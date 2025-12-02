"""
conftest.py - Global test configuration and fixtures for pytest.
"""

import pytest
from pathlib import Path
import subprocess
from unittest.mock import MagicMock

# Import the Config class and get_config function
from hippique_orchestrator.config import Config, get_config

@pytest.fixture(scope="session")
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


@pytest.fixture(scope="session")
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


@pytest.fixture(scope="module")
def mock_config(mocker):
    """
    Fixture to provide a test-specific Config object and ensure it's used globally.
    """
    # Clear the cache of get_config to ensure a fresh config is loaded for tests
    get_config.cache_clear()

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
        # Add any other config fields that might be accessed by the application
        # or its modules at a global level (e.g., in service.py, plan.py, runner.py)
        GCS_PREFIX="test-prefix",
        TICKETS_BUCKET="test-tickets-bucket",
        TICKETS_PREFIX="test-tickets-prefix",
        CALIB_PATH="test/calib/path",
        SOURCES_FILE="test-sources-file",
        RUNNER_SNAP_DIR="test-snap-dir",
        RUNNER_ANALYSIS_DIR="test-analysis-dir",
        RUNNER_OUTPUT_DIR="test-output-dir",
        USE_GCS=True,
        USE_DRIVE=False,
        SCHEDULING_MODE="tasks", # Default value from Config
    )
    
    # Patch the Config class itself so any new Config() call returns our mock instance
    mocker.patch("hippique_orchestrator.config.Config", return_value=mock_config_instance)
    
    # Also patch the config object imported in modules at the global level
    # This is crucial for modules that do `config = get_config()` at import time
    mocker.patch("hippique_orchestrator.service.config", new=mock_config_instance)
    mocker.patch("hippique_orchestrator.plan.config", new=mock_config_instance)
    mocker.patch("hippique_orchestrator.runner.config", new=mock_config_instance)
    mocker.patch("hippique_orchestrator.simulate_wrapper.config", new=mock_config_instance)
    mocker.patch("hippique_orchestrator.validator_ev.config", new=mock_config_instance)
    mocker.patch("hippique_orchestrator.analyse_courses_du_jour_enrichie.config", new=mock_config_instance)
    mocker.patch("hippique_orchestrator.gcs_client.config", new=mock_config_instance)
    mocker.patch("hippique_orchestrator.firestore_client.config", new=mock_config_instance)
    mocker.patch("hippique_orchestrator.scripts.update_excel_planning.config", new=mock_config_instance) # Added for update_excel_planning.py

    # The get_config() function itself still needs to return the mocked instance
    mocker.patch("hippique_orchestrator.config.get_config", return_value=mock_config_instance)


    return mock_config_instance

@pytest.fixture(scope="module")
def app_with_mock_config(mock_config): # This fixture ensures app is imported AFTER mock_config is active
    from hippique_orchestrator.service import app
    return app

# Fixture for TestClient setup, ensuring it uses the mocked config
@pytest.fixture(scope="module")
def client(app_with_mock_config): # Now client depends on app_with_mock_config
    """
    Test client for the FastAPI app, using a mocked configuration.
    """
    from fastapi.testclient import TestClient
    return TestClient(app_with_mock_config)