import json
import subprocess
import sys

from simulate_ev import gate_ev, simulate_ev_batch

GPI_YML = """\
BUDGET_TOTAL: 5
SP_RATIO: 0.6
COMBO_RATIO: 0.4
EV_MIN_SP: 0.20
EV_MIN_GLOBAL: 0.40
MAX_VOL_PAR_CHEVAL: 0.60
MAX_TICKETS_SP: 1
ALLOW_JE_NA: true
PAUSE_EXOTIQUES: false
OUTDIR_DEFAULT: "runs/test"
EXCEL_PATH: "modele_suivi_courses_hippiques.xlsx"
CALIB_PATH: "payout_calibration.yaml"
MODEL: "GPI v5.1"
"""


def partants_sample():

    return {
        "rc": "R1C1",
        "hippodrome": "Test",
        "date": "2025-09-10",
        "discipline": "trot",
        "runners": [
            {"id": "1", "name": "A"},
            {"id": "2", "name": "B"},
            {"id": "3", "name": "C"},
            {"id": "4", "name": "D"},
        ],        
    }

def odds_h30():
    return {"1": 2.0, "2": 3.0, "3": 4.0, "4": 5.0}


def odds_h5():
    return {"1": 2.2, "2": 3.1, "3": 4.2, "4": 6.0}


def stats_sample():
    return {
        "1": {"j_win": 1, "e_win": 1},
        "2": {"j_win": 1, "e_win": 1},
        "3": {"j_win": 1, "e_win": 1},
        "4": {"j_win": 1, "e_win": 1},
    }


def test_smoke_run(tmp_path):
    partants = partants_sample()
    h30 = odds_h30()
    h5 = odds_h5()
    stats = stats_sample()

    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats_je.json"
    partants_path = tmp_path / "partants.json"
    gpi_path = tmp_path / "gpi.yml"
    outdir = tmp_path / "out"

    h30_path.write_text(json.dumps(h30), encoding="utf-8")
    h5_path.write_text(json.dumps(h5), encoding="utf-8")
    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")
    gpi_path.write_text(GPI_YML, encoding="utf-8")

    cmd = [
        sys.executable,
        "pipeline_run.py",
        "--h30",
        str(h30_path),
        "--h5",
        str(h5_path),
        "--stats-je",
        str(stats_path),
        "--partants",
        str(partants_path),
        "--gpi",
        str(gpi_path),
        "--outdir",
        str(outdir),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr

    # artefacts
    assert (outdir / "p_finale.json").exists()
    assert (outdir / "diff_drift.json").exists()
    assert (outdir / "ligne.csv").exists()
    assert (outdir / "cmd_update_excel.txt").exists()

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    tickets = data["tickets"]
    assert len(tickets) <= 1
    stake_total = sum(t.get("stake", 0) for t in tickets)
    assert stake_total <= 5.00 + 1e-6

    # Combined payout is zero -> combo flag should be False
    cfg = {
        "BUDGET_TOTAL": 5,
        "SP_RATIO": 0.6,
        "EV_MIN_SP": 0.20,
        "EV_MIN_GLOBAL": 0.40,
        "MIN_PAYOUT_COMBOS": 10.0,
    }
    stats_ev = simulate_ev_batch(tickets, bankroll=cfg["BUDGET_TOTAL"])
    flags = gate_ev(
        cfg,
        ev_sp=float(data["ev"]["sp"]),
        ev_global=float(data["ev"]["global"]),
        min_payout_combos=stats_ev.get("combined_expected_payout", 0.0),
    )
    assert not flags["combo"]
