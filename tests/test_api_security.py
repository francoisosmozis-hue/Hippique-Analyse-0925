from fastapi.testclient import TestClient

def test_schedule_endpoint_requires_api_key(client: TestClient):
    """
    Tests that POST /schedule returns 403 Forbidden when no API key is provided.
    """
    response = client.post("/schedule", json={"dry_run": True})
    
    # In the context of our dependency, it returns 403, not 401.
    # We should assert this specific behavior.
    assert response.status_code == 403
    assert "Not authenticated" in response.text

def test_ops_run_endpoint_requires_api_key(client: TestClient):
    """
    Tests that POST /ops/run returns 403 Forbidden when no API key is provided.
    """
    response = client.post("/ops/run", params={"rc": "R1C1"})
    
    assert response.status_code == 403
    assert "Not authenticated" in response.text

def test_task_worker_endpoint_security(client: TestClient):
    """
    Tests that POST /tasks/run-phase returns 403 Forbidden when no OIDC token
    is mocked or provided. The underlying dependency will raise an exception.
    """
    payload = {
        "course_url": "http://example.com/race/1",
        "phase": "H-5",
        "date": "2025-12-25",
        "doc_id": "2025-12-25_R1C1"
    }
    response = client.post("/tasks/run-phase", json=payload)
    
    # The default behavior without a valid token mock should be a failure.
    # The verify_oidc_token dependency raises an HTTPException(403)
    assert response.status_code == 403
    assert "Not authenticated" in response.text
