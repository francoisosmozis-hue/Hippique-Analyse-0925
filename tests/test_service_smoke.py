from datetime import datetime
from zoneinfo import ZoneInfo


# Mock DocumentSnapshot class
class MockDocumentSnapshot:
    def __init__(self, id, data):
        self._id = id
        self._data = data
    @property
    def id(self): return self._id
    def to_dict(self): return self._data

def test_ping_endpoint(client):
    response = client.get("/health") # Assuming /ping is deprecated, use /health
    assert response.status_code == 200

def test_pronostics_endpoint_returns_data(client, mocker):
    """
    A smoke test to ensure the pronostics API returns a valid structure with data.
    """
    now_iso = datetime.now(ZoneInfo("UTC")).isoformat()
    mock_docs = [
        MockDocumentSnapshot("2025-01-10_R1C1", {
            "rc": "R1C1", "last_analyzed_at": now_iso,
            "tickets_analysis": {"gpi_decision": "Play"}
        })
    ]
    plan_races = [{"rc_label": "R1C1"}]
    mocker.patch("hippique_orchestrator.plan.build_plan_async", return_value=plan_races)
    mocker.patch("hippique_orchestrator.firestore_client.get_races_for_date", return_value=mock_docs)

    response = client.get("/api/pronostics?date=2025-01-10")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["counts"]["total_in_plan"] == 1
    assert data["counts"]["total_playable"] == 1
    assert data["counts"]["total_processed"] == 1
    assert len(data["pronostics"]) == 1
    assert data["pronostics"][0]["rc"] == "R1C1"
    assert data["pronostics"][0]["status"] == "playable"
