import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest


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
            {"id": "1", "name": "A", "stake": 2.0, "odds": 5.0, "p": 0.3},
            {"id": "3", "name": "C", "stake": 1.0, "odds": 3.0, "p": 0.2},
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
    results = [t.get("result") for t in data.get("tickets", [])]
    assert results == [1, 0]
    rois = [t.get("roi_reel") for t in data.get("tickets", [])]
    assert rois == [pytest.approx(4.0), pytest.approx(-1.0)]
    briers = [t.get("brier") for t in data.get("tickets", [])]
    assert briers == [pytest.approx(0.49), pytest.approx(0.04)]
    assert data["roi_reel"] == pytest.approx((10.0 - 3.0) / 3.0)
    assert data["result_moyen"] == pytest.approx(0.5)
    assert data["roi_reel_moyen"] == pytest.approx(1.5)
    assert data["brier_total"] == pytest.approx(0.53)
    assert data["brier_moyen"] == pytest.approx(0.265)

    arrivee_out = json.loads((tmp_path / "arrivee.json").read_text(encoding="utf-8"))
    assert arrivee_out["roi_reel"] == data["roi_reel"]
    assert arrivee_out["result_moyen"] == data["result_moyen"]
    assert arrivee_out["roi_reel_moyen"] == data["roi_reel_moyen"]
    assert arrivee_out["brier_total"] == data["brier_total"]
    assert arrivee_out["brier_moyen"] == data["brier_moyen"]

    ligne_path = tmp_path / "ligne_resultats.csv"
    assert ligne_path.exists()
    header, row = ligne_path.read_text(encoding="utf-8").strip().splitlines()
    header_cols = header.split(";")
    row_cols = row.split(";")
    idx_result = header_cols.index("result_moyen")
    idx_roi_ticket = header_cols.index("ROI_reel_moyen")
    idx_brier_total = header_cols.index("Brier_total")
    idx_brier_moyen = header_cols.index("Brier_moyen")
    assert float(row_cols[idx_result]) == pytest.approx(0.5)
    assert float(row_cols[idx_roi_ticket]) == pytest.approx(1.5)
    assert float(row_cols[idx_brier_total]) == pytest.approx(0.53)
    assert float(row_cols[idx_brier_moyen]) == pytest.approx(0.265)

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
    results = [t.get("result") for t in data.get("tickets", [])]
    assert results == [1, 1]
    rois = [t.get("roi_reel") for t in data.get("tickets", [])]
    assert rois == [pytest.approx(4.0), pytest.approx(2.0)]
    briers = [t.get("brier") for t in data.get("tickets", [])]
    assert briers == [pytest.approx(0.49), pytest.approx(0.64)]
    assert data["roi_reel"] == pytest.approx((13.0 - 3.0) / 3.0)
    assert data["result_moyen"] == pytest.approx(1.0)
    assert data["roi_reel_moyen"] == pytest.approx(3.0)
    assert data["brier_total"] == pytest.approx(1.13)
    assert data["brier_moyen"] == pytest.approx(0.565)


def test_post_course_missing_arrivee(tmp_path: Path):
    tickets_path = tmp_path / "tickets.json"
    tickets_path.write_text(json.dumps(sample_tickets()), encoding="utf-8")

    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent.parent / "post_course.py"),
        "--arrivee",
        str(tmp_path / "missing_arrivee.json"),
        "--tickets",
        str(tickets_path),
        "--outdir",
        str(tmp_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "Arrivee file not found" in res.stdout

    arrivee_json = tmp_path / "arrivee.json"
    assert arrivee_json.exists()
    arrivee_out = json.loads(arrivee_json.read_text(encoding="utf-8"))
    assert arrivee_out["status"] == "missing"
    assert arrivee_out["rc"] == sample_tickets()["meta"]["rc"]
    assert arrivee_out["date"] == date.today().isoformat()

    arrivee_csv = tmp_path / "arrivee.csv"
    assert arrivee_csv.exists()
    csv_lines = arrivee_csv.read_text(encoding="utf-8").strip().splitlines()
    assert csv_lines[0] == "status;rc;date"
    assert csv_lines[1].split(";") == [
        "missing",
        sample_tickets()["meta"]["rc"],
        date.today().isoformat(),
    ]

    assert not (tmp_path / "cmd_update_excel.txt").exists()
    assert not (tmp_path / "ligne_resultats.csv").exists()
