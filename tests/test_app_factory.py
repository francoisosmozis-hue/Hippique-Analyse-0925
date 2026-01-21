"""
tests/test_app_factory.py - Tests for the FastAPI application factory.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_app import create_app


def test_create_app_returns_fastapi_instance():
    """
    Tests that the create_app function returns an instance of FastAPI.
    """
    app = create_app()
    assert isinstance(app, FastAPI)


def test_health_check_endpoint_exists(client: TestClient):
    """
    Tests that the /health endpoint is available and returns a 200 OK response.
    This is a basic integration test to ensure the app is correctly configured.
    """
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
