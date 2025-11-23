import os
import httpx
from httpx import AsyncClient
from fastapi.testclient import TestClient

# TZ cohérent
os.environ["TZ"] = "Europe/Paris"

# Imports app & modules (le sys.path vers src est géré par tests/conftest.py)
from src import plan
from src.service import app

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
async def test_schedule_to_run_flow(monkeypatch, mocker):
    # 1) Mock la fonction de construction du plan ASYNCHRONE
    mock_plan_result = [
        {
            "r_label": "R1",
            "c_label": "C1",
            "time_local": "14:30",
            "course_url": "https://www.example.com/R1C1",
            "date": "2025-10-26"
        }
    ]

    async def mock_build_plan_async(date):
        return mock_plan_result

    monkeypatch.setattr(plan, "build_plan_async", mock_build_plan_async)

    # Mock de l'infra GCP pour éviter l'erreur de credentials
    mocker.patch("src.scheduler.get_tasks_client")

    # 2) Mock l'appel HTTP interne que fait /schedule vers /tasks/bootstrap-day
    mock_post = mocker.patch("httpx.AsyncClient.post")
    # Simule une réponse réussie de l'endpoint bootstrap
    mock_post.return_value = httpx.Response(202, json={"ok": True, "message": "Bootstrap initiated."})

    # 3) Appeler /schedule
    resp = client.post("/schedule", json={})
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data.get("ok") is True, f"La réponse de l'API n'est pas OK: {data}"
