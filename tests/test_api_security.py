"""
Tests for API security and authentication dependencies.
"""
from fastapi.testclient import TestClient


def test_schedule_endpoint_is_protected_by_api_key(client: TestClient, mocker):
    """
    Given authentication is required,
    When the X-API-KEY header is missing for the /schedule endpoint,
    Then the request should be denied with a 403 error.
    """
    mocker.patch("hippique_orchestrator.config.REQUIRE_AUTH", True)
    
    response = client.post("/schedule", json={"dry_run": True})
    
    assert response.status_code == 403
    assert "Invalid or missing API Key" in response.text


def test_api_key_authentication(client: TestClient, mocker, monkeypatch):
    """
    Tests the API key authentication logic for both failure and success cases.
    """
    # 1. Test Failure Cases (key missing or wrong)
    mocker.patch("hippique_orchestrator.config.REQUIRE_AUTH", True)
    
    response_no_header = client.post("/schedule", json={"dry_run": True})
    assert response_no_header.status_code == 403, "Should fail without API key"
    
    response_wrong_key = client.post("/schedule", json={"dry_run": True}, headers={"X-API-KEY": "wrong-key"})
    assert response_wrong_key.status_code == 403, "Should fail with wrong API key"

    # 2. Test Success Case (valid key)
    # We patch the key in the 'auth' module where it's actually checked.
    mocker.patch("hippique_orchestrator.auth.config.INTERNAL_API_SECRET", "test-key")
    mocker.patch("hippique_orchestrator.service.plan.build_plan_async", return_value=[]) # Isolate from plan logic

    response_good_key = client.post("/schedule", json={"dry_run": True, "date": "2025-01-01"}, headers={"X-API-KEY": "test-key"})
    assert response_good_key.status_code == 200, "Should succeed with correct API key"
    assert "No races found" in response_good_key.json()["message"]

    # 3. Test Invalid Key with Auth Required
    response_invalid_key = client.post("/schedule", json={"dry_run": True}, headers={"X-API-KEY": "invalid-key"})
    assert response_invalid_key.status_code == 403, "Should fail with an invalid API key"





def test_ops_run_endpoint_security(client: TestClient, mocker):
    """
    Given authentication is required,
    When the X-API-KEY header is missing or incorrect for the /ops/run endpoint,
    Then the request should be denied with a 403 error.
    """
    mocker.patch("hippique_orchestrator.config.REQUIRE_AUTH", True)
    
    response_no_header = client.post("/ops/run?rc=R1C1")
    assert response_no_header.status_code == 403
    assert "Invalid or missing API Key" in response_no_header.text
    
    response_wrong_key = client.post("/ops/run?rc=R1C1", headers={"X-API-KEY": "wrong-key"})
    assert response_wrong_key.status_code == 403
    assert "Invalid or missing API Key" in response_wrong_key.text


def test_ops_status_endpoint_security(client: TestClient, mocker):
    """
    Given authentication is required,
    When the X-API-KEY header is missing for the /ops/status endpoint,
    Then the request should be denied with a 403 error.
    """
    mocker.patch("hippique_orchestrator.config.REQUIRE_AUTH", True)
    
    response_no_header = client.get("/ops/status?date=2025-01-01")
    assert response_no_header.status_code == 403
    assert "Invalid or missing API Key" in response_no_header.text


def test_api_key_not_required(client: TestClient, mocker):
    """
    Given authentication is NOT required (default test setting),
    When no API key is provided,
    Then the request should be successful.
    """
    # The 'mock_config_values' fixture in conftest.py already sets REQUIRE_AUTH to False.
    # We just need to mock the downstream call to isolate the test.
    mocker.patch("hippique_orchestrator.service.plan.build_plan_async", return_value=[]) # Isolate from plan logic

    response = client.post("/schedule", json={"dry_run": True, "date": "2025-01-01"})
    
    assert response.status_code == 200
    assert "No races found in plan" in response.json()["message"]


def test_task_worker_endpoint_security(client: TestClient, mocker): # Added mocker
    """
    Tests that POST /tasks/run-phase returns 403 Forbidden when no OIDC token
    is mocked or provided.
    """
    # Mocking downstream calls to isolate security test
    mocker.patch("hippique_orchestrator.api.tasks.run_course", new_callable=mocker.AsyncMock, return_value=mocker.MagicMock(**{"ok": False, "error": "security_test"})) # Mock for run_course
    payload = {
        "course_url": "http://example.com/2025-12-25/R1C1-test", # Updated URL to be parseable
        "phase": "H-5",
        "date": "2025-12-25",
        "doc_id": "2025-12-25_R1C1"
    }
    response = client.post("/tasks/run-phase", json=payload)
    
    assert response.status_code == 403
    assert "Not authenticated" in response.text


def test_task_worker_valid_token(client: TestClient, mocker):
    """
    Given a valid OIDC token, the task worker endpoint should process the request.
    """
    mocker.patch("google.oauth2.id_token.verify_oauth2_token", return_value={"email": "test@example.com"})
    # Mocking downstream calls to isolate security test
    mocker.patch("hippique_orchestrator.api.tasks.run_course", return_value={"ok": True, "gpi_decision": "test_success"}) # Mock for run_course
    
    headers = {"Authorization": "Bearer fake-token"}
    payload = { "course_url": "http://example.com/2025-01-01/R1C1-test", "phase": "H-5", "date": "2025-01-01", "doc_id": "2025-01-01_R1C1" } # Updated URL
    
    response = client.post("/tasks/run-phase", json=payload, headers=headers)
    
    assert response.status_code == 200
    assert response.json()["gpi_decision"] == "test_success"


def test_task_worker_google_auth_fails(client: TestClient, mocker):
    """
    Given Google Auth raises a ValueError, the endpoint should return 401.
    """
    mocker.patch("google.oauth2.id_token.verify_oauth2_token", side_effect=ValueError("Token expired"))
    # Mocking downstream calls to isolate security test
    mocker.patch("hippique_orchestrator.api.tasks.run_course", new_callable=mocker.AsyncMock, return_value=mocker.MagicMock(**{"ok": False, "error": "security_test"})) # Mock for run_course
    
    headers = {"Authorization": "Bearer expired-token"}
    payload = { "course_url": "http://example.com/2025-01-01/R1C1-test", "phase": "H-5", "date": "2025-01-01" } # Updated URL

    response = client.post("/tasks/run-phase", json=payload, headers=headers)
    
    assert response.status_code == 401
    assert "Token validation failed: Token expired" in response.json()["detail"]


def test_task_worker_invalid_token_scheme(client: TestClient, mocker): # Added mocker
    """
    Given a token with an invalid scheme (not 'Bearer'), the endpoint should return 401.
    """
    # Mocking downstream calls to isolate security test
    mocker.patch("hippique_orchestrator.api.tasks.run_course", new_callable=mocker.AsyncMock, return_value=mocker.MagicMock(**{"ok": False, "error": "security_test"})) # Mock for run_course
    headers = {"Authorization": "Basic fake-token"}
    payload = { "course_url": "http://example.com/2025-01-01/R1C1-test", "phase": "H-5", "date": "2025-01-01" } # Updated URL

    response = client.post("/tasks/run-phase", json=payload, headers=headers)
    
    assert response.status_code == 401
    assert "Invalid token scheme" in response.json()["detail"]


def test_snapshot_9h_endpoint_security(client: TestClient):
    """
    Tests that POST /tasks/snapshot-9h returns 403 Forbidden when no OIDC token
    is mocked or provided.
    """
    payload = { "date": "2025-12-25" }
    response = client.post("/tasks/snapshot-9h", json=payload)
    assert response.status_code == 403
    assert "Not authenticated" in response.text

def test_bootstrap_day_endpoint_security(client: TestClient):
    """
    Tests that POST /tasks/bootstrap-day returns 403 Forbidden when no OIDC token
    is mocked or provided.
    """
    payload = { "date": "2025-12-25" }
    response = client.post("/tasks/bootstrap-day", json=payload)
    assert response.status_code == 403
    assert "Not authenticated" in response.text

def test_ops_run_endpoint_accessible_when_auth_not_required(client: TestClient, mocker):
    """
    Given authentication is NOT required,
    When no API key is provided for /ops/run,
    Then the request should be successful.
    """
    # REQUIRE_AUTH is False by default in the test client fixture
    mocker.patch("hippique_orchestrator.service.plan.build_plan_async", new_callable=mocker.AsyncMock, return_value=[{"r_label": "R1", "c_label": "C1", "url": "http://example.com"}])
    mocker.patch("hippique_orchestrator.service.analysis_pipeline.run_analysis_for_phase", new_callable=mocker.AsyncMock, return_value={"status": "ok", "gpi_decision": "test"})
    mocker.patch("hippique_orchestrator.service.firestore_client.update_race_document", return_value=None)
    
    response = client.post("/ops/run?rc=R1C1")
    assert response.status_code == 200

def test_ops_status_endpoint_accessible_when_auth_not_required(client: TestClient, mocker):
    """
    Given authentication is NOT required,
    When no API key is provided for /ops/status,
    Then the request should be successful.
    """
    # REQUIRE_AUTH is False by default in the test client fixture
    mocker.patch("hippique_orchestrator.service.plan.build_plan_async", new_callable=mocker.AsyncMock, return_value=[])
    mocker.patch("hippique_orchestrator.service.firestore_client.get_processing_status_for_date", return_value={"status": "ok"})
    
    response = client.get("/ops/status?date=2025-01-01")
    assert response.status_code == 200
