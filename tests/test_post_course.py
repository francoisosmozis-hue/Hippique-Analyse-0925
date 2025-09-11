import json
import subprocess
import sys
import pytest
from pathlib import Path


def sample_tickets():
    return {
        "meta": {
            "rc": "R1C1",
            "hippodrome": "Test",
            "date": "2025-09-10",
            "discipline": "trot",
            "model": "GPI",
        },
        "tickets": [
            {"id": "1", "name": "A", "stake": 2.0, "odds": 5.0},
            {"id": "3", "name": "C", "stake": 1.0, "odds": 3.0},
        ],
    }


def sample_arrivee():
    return {"rc": "R1C1", "result": ["1", "2", "3"]}


def test_post_course_flow(tmp_path: Path):
    tickets_path = tmp_path / "tickets.json"
    arrivee_path = tmp_path / "arrivee_officielle.json"
    tickets_path.write_text(json.dumps(sample_tickets()), encoding="utf-8")
    arrivee_path.write_text(json.dumps(sample_arrivee()), encoding="utf-8")

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent.parent / "post_course.py"),
        "--arrivee",
        str(arrivee_path),
        "--tickets",
        str(tickets_path),
        "--outdir",
        str(tmp_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr

    data = json.loads(tickets_path.read_text(encoding="utf-8"))
    gains = [t.get("gain_reel", 0) for t in data.get("tickets", [])]
    assert gains == [10.0, 0.0]
    assert data["roi_reel"] == pytest.approx((10.0 - 3.0) / 3.0)

    arrivee_out = json.loads((tmp_path / "arrivee.json").read_text(encoding="utf-8"))
    assert arrivee_out["roi_reel"] == data["roi_reel"]
    assert (tmp_path / "ligne_resultats.csv").exists()
    cmd_txt = (tmp_path / "cmd_update_excel.txt").read_text(encoding="utf-8")
    assert "update_excel_with_results.py" in cmd_txt


def test_post_course_flow_multi_places(tmp_path: Path):
    tickets_path = tmp_path / "tickets.json"
    arrivee_path = tmp_path / "arrivee_officielle.json"
    tickets_path.write_text(json.dumps(sample_tickets()), encoding="utf-8")
    arrivee_path.write_text(json.dumps(sample_arrivee()), encoding="utf-8")

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent.parent / "post_course.py"),
        "--arrivee",
        str(arrivee_path),
        "--tickets",
        str(tickets_path),
        "--outdir",
        str(tmp_path),
        "--places",
        "3",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr

    data = json.loads(tickets_path.read_text(encoding="utf-8"))
    gains = [t.get("gain_reel", 0) for t in data.get("tickets", [])]
    assert gains == [10.0, 3.0]
    assert data["roi_reel"] == pytest.approx((13.0 - 3.0) / 3.0)
