import pytest
from starlette.testclient import TestClient

def test_read_main(client: TestClient):
    response = client.get("/pronostics")
    assert response.status_code == 200
    assert "Pronostics Hippiques" in response.text
