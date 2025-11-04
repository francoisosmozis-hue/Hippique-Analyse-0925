import os
from fastapi.testclient import TestClient

# TZ cohérent
os.environ["TZ"] = "Europe/Paris"

# Imports app & modules (le sys.path vers src est géré par tests/conftest.py)
from src.service import app
import src.plan as plan
import src.pipeline_run as pipeline_run

client = TestClient(app)

# HTML minimal conforme au parseur boturfers de plan.py
BOTURFERS_HTML = """
<div class="card shadow mb-4">
  <h2 class="text-primary">R1 - Vincennes</h2>
  <table><tbody>
    <tr>
      <th><a href="/courses/2025-10-26/vincennes/course-C1">C1</a></th>
      <td></td>
      <td></td>
      <td class="d-none d-lg-table-cell">Trot attelé</td>
      <td><span class="race-time">14h30</span></td>
    </tr>
  </tbody></table>
</div>
"""

import pytest

BOTURFERS_HTML = """..."""  # Gardé pour référence, mais non utilisé

@pytest.mark.asyncio
async def test_schedule_to_run_flow(monkeypatch):
    # 1) Mock la fonction de construction du plan ASYNCHRONE
    mock_plan_result = [
        {
            "r_label": "R1",
            "c_label": "C1",
            "time_local": "14:30",
            "course_url": "https://www.example.com/R1C1"
        }
    ]

    async def mock_build_plan_async(date):
        return mock_plan_result

    monkeypatch.setattr(plan, "build_plan_async", mock_build_plan_async)

    # 2) /schedule
    resp = client.post("/schedule", json={})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("ok") is True, f"La réponse de l'API n'est pas OK: {data}"

    plan_items = data.get("plan", [])
    assert len(plan_items) > 0, "Le plan ne devrait pas être vide"
    item = plan_items[0]
    assert item["r_label"] == "R1"

    # 3) /run (Vérifier que l'endpoint existe)
    run_req = {
        "course_url": item["course_url"],
        "phase": "H30",
        "date": "2025-10-26",
    }
    r2 = client.post("/run", json=run_req)
    assert r2.status_code == 200, r2.text
    out = r2.json()
    assert out["ok"] is False
