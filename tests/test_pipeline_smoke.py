import json
import subprocess
import sys

import yaml
import pytest

from simulate_ev import allocate_dutching_sp, gate_ev, simulate_ev_batch
from pipeline_run import build_p_true, load_yaml

GPI_YML = """\
BUDGET_TOTAL: 5
SP_RATIO: 0.6
COMBO_RATIO: 0.4
EV_MIN_SP: 0.20
EV_MIN_GLOBAL: 0.40
ROR_MAX: 0.05
MAX_VOL_PAR_CHEVAL: 0.60
MAX_TICKETS_SP: 1
ALLOW_JE_NA: true
PAUSE_EXOTIQUES: false
OUTDIR_DEFAULT: "runs/test"
EXCEL_PATH: "modele_suivi_courses_hippiques.xlsx"
CALIB_PATH: "payout_calibration.yaml"
DRIFT_COEF: 0.05
JE_BONUS_COEF: 0.001
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

    ev_sum = sum(t.get("ev_ticket", 0) for t in tickets)
    assert data["ev"]["sp"] == pytest.approx(ev_sum)
    roi_sp = ev_sum / stake_total if stake_total else 0.0
    data_roi = float(data["ev"]["sp"]) / stake_total if stake_total else 0.0
    assert data_roi == pytest.approx(roi_sp)

    # Ensure selected ticket has the highest individual EV
    cfg_full = yaml.safe_load(GPI_YML)
    cfg_full["MIN_STAKE_SP"] = 0.1
    p_true = build_p_true(cfg_full, partants["runners"], h5, h30, stats)
    runners = [
        {
            "id": str(r["id"]),
            "name": r.get("name", str(r["id"])),
            "odds": float(h5[str(r["id"])]) if str(r["id"]) in h5 else 0.0,
            "p": float(p_true[str(r["id"])]) if str(r["id"]) in p_true else 0.0,
        }
        for r in partants["runners"]
        if str(r["id"]) in h5 and str(r["id"]) in p_true
    ]
    exp_tickets, _ = allocate_dutching_sp(cfg_full, runners)
    exp_tickets.sort(key=lambda t: t["ev_ticket"], reverse=True)
    if tickets:
        assert tickets[0]["id"] == exp_tickets[0]["id"]

    # Combined payout is zero -> combo flag should be False and a high ROI
    # threshold should block SP tickets
    cfg = {
        "BUDGET_TOTAL": 5,
        "SP_RATIO": 0.6,
        "EV_MIN_SP": 0.0,
        "EV_MIN_GLOBAL": 0.0,
        "ROI_MIN_SP": 0.5,
        "ROI_MIN_GLOBAL": 0.5,
        "MIN_PAYOUT_COMBOS": 10.0,
        "ROR_MAX": 1.0,
    }
    stats_ev = simulate_ev_batch(tickets, bankroll=cfg["BUDGET_TOTAL"])
    flags = gate_ev(
        cfg,
        ev_sp=float(data["ev"]["sp"]),
        ev_global=float(data["ev"]["global"]),
        roi_sp=roi_sp,
        roi_global=stats_ev.get("roi", 0.0),
        min_payout_combos=stats_ev.get("combined_expected_payout", 0.0),
        risk_of_ruin=stats_ev.get("risk_of_ruin", 0.0),
    )
    assert not flags["sp"]
    assert not flags["combo"]

    cfg_ror = {
        "BUDGET_TOTAL": 5,
        "SP_RATIO": 0.6,
        "EV_MIN_SP": 0.0,
        "EV_MIN_GLOBAL": 0.0,
        "ROI_MIN_SP": 0.0,
        "ROI_MIN_GLOBAL": 0.0,
        "MIN_PAYOUT_COMBOS": 0.0,
        "ROR_MAX": 0.0,
    }
    flags_ror = gate_ev(
        cfg_ror,
        ev_sp=float(data["ev"]["sp"]),
        ev_global=float(data["ev"]["global"]),
        roi_sp=roi_sp,
        roi_global=stats_ev.get("roi", 0.0),
        min_payout_combos=stats_ev.get("combined_expected_payout", 0.0),
        risk_of_ruin=stats_ev.get("risk_of_ruin", 0.0),
    )
    assert not flags_ror["sp"]
    assert not flags_ror["combo"]



def test_drift_coef_sensitivity():
    partants = partants_sample()["runners"]
    h30 = odds_h30()
    h5 = odds_h5()
    stats = stats_sample()

    p_default = build_p_true({"JE_BONUS_COEF": 0.001}, partants, h5, h30, stats)
    p_no_drift = build_p_true({"DRIFT_COEF": 0.0, "JE_BONUS_COEF": 0.001}, partants, h5, h30, stats)

    assert abs(p_default["4"] - p_no_drift["4"]) > 1e-9


def test_negative_drift_increases_p_true():
    partants = partants_sample()["runners"]
    h30 = odds_h30()
    h5_no_drift = odds_h30()
    h5_neg = dict(h30)
    h5_neg["1"] = h30["1"] - 0.5
    stats = stats_sample()

    cfg = {"JE_BONUS_COEF": 0.001}
    p_no_drift = build_p_true(cfg, partants, h5_no_drift, h30, stats)
    p_neg = build_p_true(cfg, partants, h5_neg, h30, stats)

    assert p_neg["1"] > p_no_drift["1"]


def test_je_bonus_coef_sensitivity():
    partants = partants_sample()["runners"]
    h30 = odds_h30()
    h5 = odds_h5()
    stats = {"1": {"j_win": 5, "e_win": 0}}

    p_default = build_p_true({"JE_BONUS_COEF": 0.001}, partants, h5, h30, stats)
    p_no_bonus = build_p_true({"JE_BONUS_COEF": 0.0}, partants, h5, h30, stats)

    assert p_default["1"] > p_no_bonus["1"]


def test_invalid_config_ratio(tmp_path):
    bad_yml = GPI_YML.replace("SP_RATIO: 0.6", "SP_RATIO: 0.7").replace(
        "COMBO_RATIO: 0.4", "COMBO_RATIO: 0.5"
    )
    cfg_path = tmp_path / "gpi_bad.yml"
    cfg_path.write_text(bad_yml, encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_yaml(str(cfg_path))
