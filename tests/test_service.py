
import pytest
from fastapi.testclient import TestClient
import sys, pathlib, json, os, shutil

# --- Add project root to sys.path ---
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.service import app

client = TestClient(app)

@pytest.fixture(scope="module")
def setup_test_data():
    data_dir = _PROJECT_ROOT / "data"
    race_dir = data_dir / "R1C1"
    race_dir.mkdir(parents=True, exist_ok=True)

    # Create a dummy analysis file
    analysis_data = {
        "reunion": "R1",
        "course": "C1",
        "abstain": False,
        "tickets": [
            {"type": "SP", "detail": "3-5", "mise": 2.0},
            {"type": "CG", "detail": "3-5-7", "mise": 3.0}
        ],
        "validation": {
            "roi_global_est": 25.0
        }
    }
    with open(race_dir / "analysis_H5.json", "w") as f:
        json.dump(analysis_data, f)

    yield

    # Teardown
    shutil.rmtree(race_dir)

def test_health_check():
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"

def xtest_pipeline_run_success(mocker):
    # This test verifies the file-reading logic of the endpoint.
    # We mock subprocess.run as it's not relevant to this path.
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "Pipeline executed successfully"
    mock_run.return_value.stderr = ""

    # Create a dummy analysis file for the endpoint to find
    data_dir = _PROJECT_ROOT / "data" / "R1C2"
    data_dir.mkdir(parents=True, exist_ok=True)
    analysis_data = {
        "abstain": False,
        "tickets": [{"type": "SP", "detail": "1-2", "mise": 5.0}],
        "validation": {"roi_global_est": 30.0}
    }
    with open(data_dir / "analysis_H5.json", "w") as f:
        json.dump(analysis_data, f)

    response = client.post("/pipeline/run?use_file_logic=true", json={"reunion": "R1", "course": "C2", "phase": "H5", "budget": 5.0})
    
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] == "ok"
    assert not response_json["abstain"]
    assert len(response_json["tickets"]) == 1
    assert response_json["roi_global_est"] == 30.0

    # Teardown
    shutil.rmtree(data_dir)

def xtest_tickets_endpoint(setup_test_data):
    response = client.get("/tickets")
    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "<h1>Today's Tickets</h1>" in content
    assert "<h2>R1C1</h2>" in content
    assert "ROI Global Est: 25.0%" in content
    assert "<li>SP - 3-5 - 2.0€</li>" in content
    assert "<li>CG - 3-5-7 - 3.0€</li>" in content
