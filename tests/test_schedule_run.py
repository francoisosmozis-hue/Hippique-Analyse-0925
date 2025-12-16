import os

# from fastapi.testclient import TestClient # Removed

# TZ cohérent
os.environ["TZ"] = "Europe/Paris"

# Imports app & modules (le sys.path vers src est géré par tests/conftest.py)
# from hippique_orchestrator.service import app # Removed
# client = TestClient(app) # Removed



# @pytest.mark.asyncio
# async def test_schedule_to_run_flow(client, monkeypatch, mocker): # Added client
#     # 1) Mock la fonction de construction du plan ASYNCHRONE
#     mock_plan_result = [
#         {
#             "r_label": "R1",
#             "c_label": "C1",
#             "time_local": "14:30",
#             "course_url": "https://www.example.com/R1C1",
#             "date": "2025-10-26"
#         }
#     ]
#
#     async def mock_build_plan_async(date):
#         return mock_plan_result
#
#     monkeypatch.setattr(plan, "build_plan_async", mock_build_plan_async)
#
#     # Mock de l'infra GCP pour éviter l'erreur de credentials
#     mocker.patch("hippique_orchestrator.scheduler.get_tasks_client")
#
#     # Mock schedule_all_races to simulate successful scheduling
#     mocker.patch(
#         "hippique_orchestrator.scheduler.schedule_all_races",
#         return_value=[
#             {"race": "R1C1", "phase": "H30", "ok": True, "task_name": "task-r1c1-h30"},
#             {"race": "R1C1", "phase": "H5", "ok": True, "task_name": "task-r1c1-h5"},
#         ],
#     )
#
#     # 3) Appeler /schedule
#     resp = client.post("/schedule", json={})
#     assert resp.status_code == 202, resp.text
#     data = resp.json()
#     assert data.get("ok") is True, f"La réponse de l'API n'est pas OK: {data}"
