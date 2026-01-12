from fastapi.testclient import TestClient

from hippique_orchestrator.service import app

client = TestClient(app)


def test_get_pronostics_data_invalid_date():
    """
    Tests that the /api/pronostics endpoint returns a 422 error
    for an invalid date format.
    """
    response = client.get("/api/pronostics?date=invalid-date")
    assert response.status_code == 422
    assert "Invalid date format" in response.json()["detail"]


def test_get_pronostics_data_plan_only(mocker):
    """
    Tests the /api/pronostics endpoint when there are races in the plan
    but no data in Firestore.
    """
    mocker.patch("hippique_orchestrator.firestore_client.get_races_for_date", return_value=[])
    mocker.patch(
        "hippique_orchestrator.plan.build_plan_async",
        return_value=[
            {
                "r_label": "R1",
                "c_label": "C1",
                "name": "PRIX DE TEST",
                "time_local": "13:50",
            }
        ],
    )

    response = client.get("/api/pronostics?date=2025-01-01")
    assert response.status_code == 200
    data = response.json()

    assert data["source"] == "plan_fallback"
    assert len(data["races"]) == 1
    p = data["races"][0]
    assert p["rc"] == "R1C1"
    assert p["nom"] == "PRIX DE TEST"
    assert p["status"] == "pending"
