from fastapi.testclient import TestClient

from hippique_orchestrator.service import app

client = TestClient(app)


def test_read_main():
    response = client.get("/pronostics")
    assert response.status_code == 200
    assert "Pronostics Hippiques" in response.text
