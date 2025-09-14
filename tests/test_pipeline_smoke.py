import json
import subprocess
import sys
import os

import yaml
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulate_ev import allocate_dutching_sp, gate_ev, simulate_ev_batch
from pipeline_run import build_p_true, compute_drift_dict, load_yaml

GPI_YML = """\
BUDGET_TOTAL: 5
SP_RATIO: 0.6
COMBO_RATIO: 0.4
EV_MIN_SP: 0.20
EV_MIN_GLOBAL: 0.40
ROI_MIN_GLOBAL: 0.20
ROR_MAX: 0.05
MAX_VOL_PAR_CHEVAL: 0.60
MIN_PAYOUT_COMBOS: 10.0
MAX_TICKETS_SP: 1
ALLOW_JE_NA: true
PAUSE_EXOTIQUES: false
OUTDIR_DEFAULT: "runs/test"
EXCEL_PATH: "modele_suivi_courses_hippiques.xlsx"
CALIB_PATH: "payout_calibration.yaml"
DRIFT_COEF: 0.05
JE_BONUS_COEF: 0.001
MIN_STAKE_SP: 0.10
ROUND_TO_SP: 0.10
KELLY_FRACTION: 0.5
SHARPE_MIN: 0.0
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
            {"id": "5", "name": "E"},
            {"id": "6", "name": "F"},
        ],
    }

def odds_h30():
    return {"1": 2.0, "2": 3.0, "3": 4.0, "4": 5.0, "5": 8.0, "6": 10.0}


def odds_h5():
    return {"1": 2.2, "2": 3.1, "3": 4.2, "4": 6.0, "5": 9.0, "6": 11.0}


def stats_sample():
    return {
        "1": {"j_win": 1, "e_win": 1},
        "2": {"j_win": 1, "e_win": 1},
        "3": {"j_win": 1, "e_win": 1},
        "4": {"j_win": 1, "e_win": 1},
        "5": {"j_win": 1, "e_win": 1},
        "6": {"j_win": 1, "e_win": 1},
    }


def test_drift_missing_snapshots():
    """Ensure drift dict reports ids absent from either snapshot."""
    h30 = {"1": 2.0, "2": 3.0}
    h5 = {"2": 3.1, "3": 4.0}
    id2name = {"1": "A", "2": "B", "3": "C"}
    res = compute_drift_dict(h30, h5, id2name)
    assert set(res["missing_h30"]) == {"3"}
    assert set(res["missing_h5"]) == {"1"}


def test_drift_filtering_topn(tmp_path):
    """Drifts should be filtered by ``top_n`` and ``min_delta``."""
    h30 = {"1": 2.0, "2": 5.0, "3": 4.0, "4": 10.0}
    h5 = {"1": 4.0, "2": 2.0, "3": 5.0, "4": 8.0}
    id2name = {"1": "A", "2": "B", "3": "C", "4": "D"}
    res = compute_drift_dict(h30, h5, id2name, top_n=1, min_delta=1.5)
    diff = res["drift"]
    assert len(diff) == 2
    assert any(r["delta"] > 0 for r in diff)
    assert any(r["delta"] < 0 for r in diff)
    assert all(abs(r["delta"]) >= 1.5 for r in diff)

def test_snapshot_cli(tmp_path):
    """Ensure snapshot subcommand renames snapshot files correctly."""
    src = tmp_path / "h30.json"
    src.write_text("{}", encoding="utf-8")

    cmd = [
        sys.executable,
        "pipeline_run.py",
        "snapshot",
        "--when",
        "h30",
        "--meeting",
        "R1",
        "--race",
        "C1",
        "--outdir",
        str(tmp_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr

    dest = tmp_path / "R1C1-h30.json"
    assert dest.exists()
    assert json.loads(dest.read_text(encoding="utf-8")) == {}

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
    diff_path = tmp_path / "diff.json"

    h30_path.write_text(json.dumps(h30), encoding="utf-8")
    h5_path.write_text(json.dumps(h5), encoding="utf-8")
    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")
    gpi_path.write_text(GPI_YML, encoding="utf-8")

    diff_path.write_text("{}", encoding="utf-8")

    cmd = [
        sys.executable,
        "pipeline_run.py",
        "analyse",
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
        "--diff",
        str(diff_path),
        "--budget",
        "5",
        "--ev-global",
        "0.40",
        "--roi-global",
        "0.40",
        "--max-vol",
        "0.60",
        "--allow-je-na",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr

    # artefacts
    assert (outdir / "p_finale.json").exists()
    assert (outdir / "diff_drift.json").exists()
    assert (outdir / "ligne.csv").exists()
    assert (outdir / "cmd_update_excel.txt").exists()

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    assert data["meta"]["snapshots"] == "H30,H5"
    assert data["meta"]["drift_top_n"] == 5
    assert data["meta"]["drift_min_delta"] == 0.8
    diff_params = json.loads(
        (outdir / "diff_drift.json").read_text(encoding="utf-8")
    )["params"]
    assert diff_params == {"snapshots": "H30,H5", "top_n": 5, "min_delta": 0.8}
    tickets = data["tickets"]
    assert len(tickets) <= 1
    stake_total = sum(t.get("stake", 0) for t in tickets)
    assert stake_total <= 5.00 + 1e-6

    ev_sum = sum(t.get("ev_ticket", 0) for t in tickets)
    assert data["ev"]["sp"] == pytest.approx(ev_sum)
    roi_sp = ev_sum / stake_total if stake_total else 0.0
    assert data["ev"]["roi_sp"] == pytest.approx(roi_sp)

    if tickets:
        stats_ev = simulate_ev_batch(tickets, bankroll=5)
    else:
        stats_ev = {"ev": 0.0, "roi": 0.0, "risk_of_ruin": 0.0, "clv": 0.0}
    assert data["ev"]["global"] == pytest.approx(stats_ev.get("ev", 0.0))
    assert data["ev"]["roi_global"] == pytest.approx(stats_ev.get("roi", 0.0))
    assert data["ev"]["risk_of_ruin"] == pytest.approx(
        stats_ev.get("risk_of_ruin", 0.0)
    )
    assert data["ev"]["clv_moyen"] == pytest.approx(stats_ev.get("clv", 0.0))
    cfg_full = yaml.safe_load(GPI_YML)
    assert cfg_full["MIN_STAKE_SP"] == 0.10
    assert cfg_full["ROUND_TO_SP"] == 0.10
    assert cfg_full["KELLY_FRACTION"] == 0.5
    assert cfg_full["SHARPE_MIN"] == 0.0
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



def test_reallocate_combo_budget_to_sp(tmp_path):
    partants = partants_sample()
    h30 = odds_h30()
    h5 = odds_h5()
    stats = stats_sample()
    stats["4"] = {"j_win": 5000, "e_win": 0}

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

    gpi_txt = (
        GPI_YML.replace("EV_MIN_SP: 0.20", "EV_MIN_SP: 0.0")
        .replace("EV_MIN_GLOBAL: 0.40", "EV_MIN_GLOBAL: 10.0")
        .replace("ROR_MAX: 0.05", "ROR_MAX: 1.0")
    )
    gpi_path.write_text(gpi_txt, encoding="utf-8")

    diff_path = tmp_path / "diff.json"
    diff_path.write_text("{}", encoding="utf-8")

    cmd = [
        sys.executable,
        "pipeline_run.py",
        "analyse",
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
        "--diff",
        str(diff_path),
        "--budget",
        "5",
        "--ev-global",
        "10.0",
        "--roi-global",
        "0.40",
        "--max-vol",
        "0.60",
        "--allow-je-na",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "Blocage combinés" in res.stdout

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    tickets = data["tickets"]
    assert tickets, "expected at least one SP ticket"

    # Expected allocation when combo budget is reassigned to SP
    cfg_full = yaml.safe_load(gpi_txt)
    assert cfg_full["MIN_STAKE_SP"] == 0.10
    assert cfg_full["ROUND_TO_SP"] == 0.10
    assert cfg_full["KELLY_FRACTION"] == 0.5
    assert cfg_full["SHARPE_MIN"] == 0.0
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
    cfg_full_sp = dict(cfg_full)
    cfg_full_sp["SP_RATIO"] = cfg_full["SP_RATIO"] + cfg_full["COMBO_RATIO"]
    exp_tickets, _ = allocate_dutching_sp(cfg_full_sp, runners)
    exp_tickets.sort(key=lambda t: t["ev_ticket"], reverse=True)
    assert tickets[0]["ev_ticket"] == pytest.approx(exp_tickets[0]["ev_ticket"])


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
