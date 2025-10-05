import argparse
import copy
import json
import subprocess
import sys
import os

import yaml
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pipeline_run
import validator_ev
from simulate_ev import allocate_dutching_sp, gate_ev, simulate_ev_batch
from pipeline_run import build_p_true, compute_drift_dict
from config.config_loader import load_config as load_yaml

GPI_YML = """
BUDGET_TOTAL: 5
SP_RATIO: 0.6
COMBO_RATIO: 0.4
EV_MIN_SP: 0.20
EV_MIN_GLOBAL: 0.40
ROI_MIN_GLOBAL: 0.20
ROR_MAX: 0.05
MAX_VOL_PAR_CHEVAL: 0.60
MIN_PAYOUT_COMBOS: 10.0
correlation_penalty: 0.85
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
    return {
        "runners": [
            {"id": "1", "odds": 2.0},
            {"id": "2", "odds": 3.0},
            {"id": "3", "odds": 4.0},
            {"id": "4", "odds": 5.0},
            {"id": "5", "odds": 8.0},
            {"id": "6", "odds": 10.0},
        ]
    }


def odds_h5():
    return {
        "runners": [
            {"id": "1", "odds": 2.2},
            {"id": "2", "odds": 3.1},
            {"id": "3", "odds": 4.2},
            {"id": "4", "odds": 6.0},
            {"id": "5", "odds": 9.0},
            {"id": "6", "odds": 11.0},
        ]
    }


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
    assert json.loads(dest.read_text(encoding="utf-8")) == {{}}


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
    assert data["meta"].get("validation") == {"ok": True, "reason": ""}
    assert data["meta"]["snapshots"] == "H30,H5"
    assert data["meta"]["drift_top_n"] == 5
    assert data["meta"]["drift_min_delta"] == 0.8
    diff_params = json.loads((outdir / "diff_drift.json").read_text(encoding="utf-8"))[
        "params"
    ]
    assert diff_params == {"snapshots": "H30,H5", "top_n": 5, "min_delta": 0.8}
    tickets = data["tickets"]
    assert len(tickets) <= 1
    stake_total = sum(t.get("stake", 0) for t in tickets)
    assert stake_total <= 5.00 + 1e-6

    ev_sum = sum(t.get("ev_ticket", 0) for t in tickets)
    assert data["ev"]["sp"] == pytest.approx(ev_sum)
    roi_sp = ev_sum / stake_total if stake_total else 0.0
    assert data["ev"]["roi_sp"] == pytest.approx(roi_sp)

    stake_reduction = data["ev"].get("stake_reduction", {{}})
    assert data["ev"].get("stake_reduction_applied") is False
    assert stake_reduction.get("applied") is False
    scale_factor = stake_reduction.get("scale_factor")
    if scale_factor is not None:
        assert scale_factor == pytest.approx(1.0)
    assert set(stake_reduction).issuperset({"applied", "initial", "final"})

    initial_metrics = stake_reduction.get("initial", {{}})
    final_metrics = stake_reduction.get("final", {{}})
    assert "risk_of_ruin" in initial_metrics
    assert "risk_of_ruin" in final_metrics
    if stake_reduction.get("initial_cap") is not None:
        assert stake_reduction["initial_cap"] == pytest.approx(0.60, abs=1e-6)
    if stake_reduction.get("effective_cap") is not None:
        assert stake_reduction["effective_cap"] == pytest.approx(
            stake_reduction.get("initial_cap", stake_reduction["effective_cap"])
        )
    if stake_reduction.get("iterations") is not None:
        assert stake_reduction["iterations"] in (0,)

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
            "odds": (
                float(h5["runners"][int(r["id"]) - 1]["odds"])
                if str(r["id"]) in [x["id"] for x in h5["runners"]]
                else 0.0
            ),
            "p": float(p_true[str(r["id"])]) if str(r["id"]) in p_true else 0.0,
        }
        for r in partants["runners"]
        if str(r["id"]) in [x["id"] for x in h5["runners"]] and str(r["id"]) in p_true
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


def test_pipeline_validation_failure_reports_summary(tmp_path, monkeypatch):
    invalid_partants = partants_sample()
    invalid_partants["runners"] = invalid_partants["runners"][:5]

    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats_je.json"
    partants_path = tmp_path / "partants.json"
    gpi_path = tmp_path / "gpi.yml"

    h30_path.write_text(json.dumps(odds_h30()), encoding="utf-8")
    h5_path.write_text(json.dumps(odds_h5()), encoding="utf-8")
    stats_path.write_text(json.dumps(stats_sample()), encoding="utf-8")
    partants_path.write_text(json.dumps(invalid_partants), encoding="utf-8")
    gpi_path.write_text(GPI_YML, encoding="utf-8")

    captured_summary: dict[str, object] = {{}}
    real_summary = validator_ev.summarise_validation

    def recording_summary(*validators):
        result = real_summary(*validators)
        captured_summary.clear()
        captured_summary.update(result)
        return result

    monkeypatch.setattr(pipeline_run, "summarise_validation", recording_summary)

    args = argparse.Namespace(
        h30=str(h30_path),
        h5=str(h5_path),
        stats_je=str(stats_path),
        partants=str(partants_path),
        gpi=str(gpi_path),
        outdir=str(tmp_path / "out"),
        diff=None,
        budget=None,
        ev_global=None,
        roi_global=None,
        max_vol=None,
        min_payout=None,
        allow_je_na=False,
    )

    with pytest.raises(validator_ev.ValidationError, match="Nombre de partants"):
        pipeline_run.cmd_analyse(args)

    assert captured_summary.get("ok") is False
    assert "partants" in str(captured_summary.get("reason", "")).lower()


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
    odds_h5_dict = {runner["id"]: runner["odds"] for runner in h5["runners"]}
    runners = [
        {
            "id": str(r["id"]),
            "name": r.get("name", str(r["id"])),
            "odds": (
                float(odds_h5_dict[str(r["id"])])
                if str(r["id"]) in odds_h5_dict
                else 0.0
            ),
            "p": float(p_true[str(r["id"])]) if str(r["id"]) in p_true else 0.0,
        }
        for r in partants["runners"]
        if str(r["id"]) in odds_h5_dict and str(r["id"]) in p_true
    ]
    cfg_full_sp = dict(cfg_full)
    cfg_full_sp["SP_RATIO"] = cfg_full["SP_RATIO"] + cfg_full["COMBO_RATIO"]
    exp_tickets, _ = allocate_dutching_sp(cfg_full_sp, runners)
    exp_tickets.sort(key=lambda t: t["ev_ticket"], reverse=True)
    assert tickets[0]["ev_ticket"] == pytest.approx(exp_tickets[0]["ev_ticket"])


def test_high_risk_pack_is_trimmed(tmp_path, monkeypatch):
    partants = {
        "rc": "R1C1",
        "hippodrome": "Test",
        "date": "2025-09-10",
        "discipline": "trot",
        "runners": [
            {"id": "1", "name": "Alpha"},
            {"id": "2", "name": "Bravo"},
            {"id": "3", "name": "Charlie"},
            {"id": "4", "name": "Delta"},
            {"id": "5", "name": "Echo"},
            {"id": "6", "name": "Foxtrot"},
        ],
    }
    h30 = {"runners": [{"id": str(i), "odds": 2.0 + 0.4 * i} for i in range(1, 7)]}
    h5 = {"runners": [{"id": str(i), "odds": 2.0 + 0.5 * i} for i in range(1, 7)]}
    stats = {str(i): {"j_win": 0, "e_win": 0} for i in range(1, 7)}

    gpi_txt = (
        GPI_YML.replace("BUDGET_TOTAL: 5", "BUDGET_TOTAL: 100")
        .replace("SP_RATIO: 0.6", "SP_RATIO: 1.0")
        .replace("COMBO_RATIO: 0.4", "COMBO_RATIO: 0.0")
        .replace("EV_MIN_SP: 0.20", "EV_MIN_SP: 0.0")
        .replace("EV_MIN_GLOBAL: 0.40", "EV_MIN_GLOBAL: 0.0")
        .replace("ROI_MIN_GLOBAL: 0.20", "ROI_MIN_GLOBAL: 0.0")
        .replace("ROR_MAX: 0.05", "ROR_MAX: 0.01")
        .replace("MAX_VOL_PAR_CHEVAL: 0.60", "MAX_VOL_PAR_CHEVAL: 0.90")
        .replace("KELLY_FRACTION: 0.5", "KELLY_FRACTION: 1.0")
    )

    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats.json"
    partants_path = tmp_path / "partants.json"
    gpi_path = tmp_path / "gpi.yml"
    diff_path = tmp_path / "diff.json"
    outdir = tmp_path / "out"

    h30_path.write_text(json.dumps(h30), encoding="utf-8")
    h5_path.write_text(json.dumps(h5), encoding="utf-8")
    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")
    gpi_path.write_text(gpi_txt, encoding="utf-8")
    diff_path.write_text("{}", encoding="utf-8")

    p_stub = {"1": 0.55, "2": 0.1, "3": 0.1, "4": 0.1, "5": 0.1, "6": 0.05}

    monkeypatch.setattr("pipeline_run.build_p_true", lambda *a, **k: dict(p_stub))

    def fake_apply_ticket_policy(
        cfg, runners, combo_candidates=None, combos_source=None
    ):
        tickets, _ = allocate_dutching_sp(cfg, runners)
        return tickets, [], None

    monkeypatch.setattr("pipeline_run.apply_ticket_policy", fake_apply_ticket_policy)

    cfg_loaded = load_yaml(str(gpi_path))
    odds_h5_dict = {r["id"]: r["odds"] for r in h5["runners"]}
    runners = [
        {
            "id": str(runner["id"]),
            "name": runner["name"],
            "odds": (
                float(odds_h5_dict[str(runner["id"])])
                if str(runner["id"]) in odds_h5_dict
                else 0.0
            ),
            "p": p_stub[str(runner["id"])],
        }
        for runner in partants["runners"]
    ]
    baseline_tickets, _ = allocate_dutching_sp(cfg_loaded, runners)
    baseline_stake = sum(t["stake"] for t in baseline_tickets)
    assert baseline_tickets, "expected baseline allocation"
    baseline_by_id = {t["id"]: t["stake"] for t in baseline_tickets}

    args = argparse.Namespace(
        h30=str(h30_path),
        h5=str(h5_path),
        stats_je=str(stats_path),
        partants=str(partants_path),
        gpi=str(gpi_path),
        outdir=str(outdir),
        diff=str(diff_path),
        budget=None,
        ev_global=None,
        roi_global=None,
        max_vol=None,
        min_payout=None,
        allow_je_na=True,
    )

    pipeline_run.cmd_analyse(args)

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    tickets = data["tickets"]
    assert tickets, "expected trimmed SP tickets"

    final_stake = sum(t["stake"] for t in tickets)
    assert final_stake < baseline_stake
    for ticket in tickets:
        assert ticket["stake"] < baseline_by_id.get(ticket["id"], float("inf"))

    stake_reduction = data["ev"]["stake_reduction"]
    assert data["ev"]["stake_reduction_applied"] is True
    assert stake_reduction["applied"] is True
    assert stake_reduction["scale_factor"] < 1.0
    assert stake_reduction["effective_cap"] < stake_reduction["initial_cap"]
    assert stake_reduction["iterations"] >= 1

    initial_metrics = stake_reduction["initial"]
    final_metrics = stake_reduction["final"]
    target_ror = stake_reduction.get("target") or cfg_loaded["ROR_MAX"]
    assert initial_metrics["risk_of_ruin"] > target_ror
    assert final_metrics["risk_of_ruin"] <= target_ror + 1e-9

    current_cap = stake_reduction.get("effective_cap")
    if not current_cap:
        current_cap = cfg_loaded.get("MAX_VOL_PAR_CHEVAL", 0.60)

    stats_ev = simulate_ev_batch(
        tickets,
        bankroll=cfg_loaded["BUDGET_TOTAL"],
        kelly_cap=current_cap,
    )
    assert data["ev"]["risk_of_ruin"] == pytest.approx(stats_ev["risk_of_ruin"])
    assert stats_ev["risk_of_ruin"] <= cfg_loaded["ROR_MAX"] + 1e-9


def test_combo_pack_scaled_not_removed(tmp_path, monkeypatch):
    partants = partants_sample()
    h30 = odds_h30()
    h5 = odds_h5()
    stats = stats_sample()

    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats.json"
    partants_path = tmp_path / "partants.json"
    gpi_path = tmp_path / "gpi.yml"
    diff_path = tmp_path / "diff.json"
    outdir = tmp_path / "out"

    h30_path.write_text(json.dumps(h30), encoding="utf-8")
    h5_path.write_text(json.dumps(h5), encoding="utf-8")
    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")

    gpi_txt = (
        GPI_YML.replace("BUDGET_TOTAL: 5", "BUDGET_TOTAL: 100")
        .replace("SP_RATIO: 0.6", "SP_RATIO: 0.5")
        .replace("COMBO_RATIO: 0.4", "COMBO_RATIO: 0.5")
        .replace("EV_MIN_SP: 0.20", "EV_MIN_SP: 0.0")
        .replace("EV_MIN_GLOBAL: 0.40", "EV_MIN_GLOBAL: 0.0")
        .replace("ROI_MIN_GLOBAL: 0.20", "ROI_MIN_GLOBAL: 0.0")
        .replace("MIN_PAYOUT_COMBOS: 10.0", "MIN_PAYOUT_COMBOS: 0.0")
        .replace("ROR_MAX: 0.05", "ROR_MAX: 0.02")
        .replace("MAX_VOL_PAR_CHEVAL: 0.60", "MAX_VOL_PAR_CHEVAL: 0.90")
    )
    gpi_path.write_text(gpi_txt, encoding="utf-8")
    diff_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr("tickets_builder.allow_combo", lambda *a, **k: True)
    monkeypatch.setattr(
        "pipeline_run.build_p_true",
        lambda *a, **k: {str(i): 1 / 6 for i in range(1, 7)},
    )

    cfg_loaded = load_yaml(str(gpi_path))

    sp_ticket = {
        "type": "SP",
        "id": "1",
        "name": "A",
        "odds": 2.0,
        "p": 0.55,
        "stake": 50.0,
        "ev_ticket": 50.0 * (0.55 * (2.0 - 1.0) - (1.0 - 0.55)),
    }
    combo_template = {
        "type": "CP",
        "id": "combo1",
        "p": 0.21,
        "odds": 5.0,
        "stake": 1.0,
        "ev_ticket": 1.0 * (0.21 * (5.0 - 1.0) - (1.0 - 0.21)),
    }

    def stub_apply_ticket_policy(
        cfg, runners, combo_candidates=None, combos_source=None
    ):
        return [dict(sp_ticket)], [dict(combo_template)], {"notes": [], "flags": {{}}}

    monkeypatch.setattr("pipeline_run.apply_ticket_policy", stub_apply_ticket_policy)

    args = argparse.Namespace(
        h30=str(h30_path),
        h5=str(h5_path),
        stats_je=str(stats_path),
        partants=str(partants_path),
        gpi=str(gpi_path),
        outdir=str(outdir),
        diff=str(diff_path),
        budget=None,
        ev_global=None,
        roi_global=None,
        max_vol=None,
        min_payout=None,
        allow_je_na=True,
    )

    pipeline_run.cmd_analyse(args)

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    tickets = data["tickets"]

    assert len(tickets) == 2
    assert any(t.get("type") != "SP" for t in tickets), "combo ticket should remain"

    stake_reduction = data["ev"]["stake_reduction"]
    assert data["ev"]["stake_reduction_applied"] is True
    assert stake_reduction["applied"] is True

    final_ror = data["ev"]["risk_of_ruin"]
    target_ror = stake_reduction.get("target") or 0.02
    assert final_ror <= target_ror + 1e-9

    scale_factor = stake_reduction["scale_factor"]
    assert scale_factor < 1.0
    assert stake_reduction["effective_cap"] < stake_reduction["initial_cap"]
    assert stake_reduction["iterations"] >= 1

    initial_metrics = stake_reduction["initial"]
    final_metrics = stake_reduction["final"]
    assert initial_metrics["risk_of_ruin"] > target_ror
    assert final_metrics["risk_of_ruin"] == pytest.approx(final_ror)

    sp_stake_total = sum(t["stake"] for t in tickets if t.get("type") == "SP")
    combo_stake_total = sum(t["stake"] for t in tickets if t.get("type") != "SP")
    assert sp_stake_total > 0.0
    assert combo_stake_total > 0.0

    final_total = sp_stake_total + combo_stake_total
    assert final_total == pytest.approx(stake_reduction["final"]["total_stake"])

    initial_total = stake_reduction["initial"]["total_stake"]
    assert initial_total > final_total
    assert final_total == pytest.approx(initial_total * scale_factor, rel=1e-2)

    current_cap = stake_reduction.get("effective_cap")
    if not current_cap:
        current_cap = cfg_loaded.get("MAX_VOL_PAR_CHEVAL", 0.60)
    stats_ev = simulate_ev_batch(
        tickets,
        bankroll=cfg_loaded["BUDGET_TOTAL"],
        kelly_cap=current_cap,
    )
    assert data["ev"]["risk_of_ruin"] == pytest.approx(stats_ev["risk_of_ruin"])
    assert stats_ev["risk_of_ruin"] <= target_ror + 1e-9


def test_drift_coef_sensitivity(monkeypatch):
    partants = partants_sample()["runners"]
    h30 = odds_h30()
    h5 = odds_h5()
    stats = stats_sample()

    monkeypatch.setattr("pipeline_run.load_p_true_model", lambda: None)

    odds_h30_dict = {runner["id"]: runner["odds"] for runner in h30["runners"]}
    odds_h5_dict = {runner["id"]: runner["odds"] for runner in h5["runners"]}

    p_default = build_p_true(
        {"JE_BONUS_COEF": 0.001, "DRIFT_COEF": 0.05},
        partants,
        odds_h5_dict,
        odds_h30_dict,
        stats,
    )
    p_no_drift = build_p_true(
        {"DRIFT_COEF": 0.0, "JE_BONUS_COEF": 0.001},
        partants,
        odds_h5_dict,
        odds_h30_dict,
        stats,
    )

    assert abs(p_default["4"] - p_no_drift["4"]) > 1e-9


def test_negative_drift_increases_p_true(monkeypatch):
    monkeypatch.setattr("pipeline_run.load_p_true_model", lambda: None)
    partants = partants_sample()["runners"]
    h30 = odds_h30()
    h5_no_drift = odds_h30()
    h5_neg = copy.deepcopy(h5_no_drift)
    for r in h5_neg["runners"]:
        if r["id"] == "1":
            r["odds"] -= 0.5
    stats = stats_sample()

    odds_h30_dict = {runner["id"]: runner["odds"] for runner in h30["runners"]}
    odds_h5_no_drift_dict = {
        runner["id"]: runner["odds"] for runner in h5_no_drift["runners"]
    }
    odds_h5_neg_dict = {runner["id"]: runner["odds"] for runner in h5_neg["runners"]}

    cfg = {"JE_BONUS_COEF": 0.001, "DRIFT_COEF": 0.05}
    p_no_drift = build_p_true(
        cfg, partants, odds_h5_no_drift_dict, odds_h30_dict, stats
    )
    p_neg = build_p_true(cfg, partants, odds_h5_neg_dict, odds_h30_dict, stats)

    assert pytest.approx(sum(p_no_drift.values()), rel=1e-6) == 1.0
    assert pytest.approx(sum(p_neg.values()), rel=1e-6) == 1.0
    assert p_neg["1"] > p_no_drift["1"]


def test_je_bonus_coef_sensitivity(monkeypatch):
    partants = partants_sample()["runners"]
    h30 = odds_h30()
    h5 = odds_h5()
    stats = {"1": {"j_win": 5, "e_win": 0}}

    monkeypatch.setattr("pipeline_run.load_p_true_model", lambda: None)

    odds_h30_dict = {runner["id"]: runner["odds"] for runner in h30["runners"]}
    odds_h5_dict = {runner["id"]: runner["odds"] for runner in h5["runners"]}

    p_default = build_p_true(
        {"JE_BONUS_COEF": 0.001, "DRIFT_COEF": 0.05},
        partants,
        odds_h5_dict,
        odds_h30_dict,
        stats,
    )
    p_no_bonus = build_p_true(
        {"JE_BONUS_COEF": 0.0, "DRIFT_COEF": 0.05},
        partants,
        odds_h5_dict,
        odds_h30_dict,
        stats,
    )

    assert p_default["1"] > p_no_bonus["1"]


def test_invalid_config_ratio(tmp_path):
    bad_yml = GPI_YML.replace("SP_RATIO: 0.6", "SP_RATIO: 0.7").replace(
        "COMBO_RATIO: 0.4", "COMBO_RATIO: 0.5"
    )
    cfg_path = tmp_path / "gpi_bad.yml"
    cfg_path.write_text(bad_yml, encoding="utf-8")
    load_yaml(str(cfg_path))


def test_load_yaml_ror_defaults_and_env(tmp_path, monkeypatch):
    cfg_txt = GPI_YML.replace("ROR_MAX: 0.05\n", "")
    cfg_path = tmp_path / "gpi.yml"
    cfg_path.write_text(cfg_txt, encoding="utf-8")

    cfg = load_yaml(str(cfg_path))
    assert cfg["ROR_MAX"] == pytest.approx(0.01)

    monkeypatch.setenv("ROR_MAX_TARGET", "0.123")
    cfg_env = load_yaml(str(cfg_path))
    assert cfg_env["ROR_MAX"] == pytest.approx(0.123)

    cfg_override_path = tmp_path / "gpi_override.yml"
    cfg_override_path.write_text(
        GPI_YML.replace("ROR_MAX: 0.05", "ROR_MAX: 0.02"), encoding="utf-8"
    )
    cfg_override = load_yaml(str(cfg_override_path))
    assert cfg_override["ROR_MAX"] == pytest.approx(0.123)


def test_load_yaml_config_aliases(tmp_path):
    cfg_txt = (
        GPI_YML.replace("BUDGET_TOTAL", "TotalBudget")
        .replace("SP_RATIO", "simpleShare")
        .replace("COMBO_RATIO", "comboShare")
        .replace("MAX_VOL_PAR_CHEVAL", "maxStakePerHorse")
    )
    cfg_path = tmp_path / "gpi_alias.yml"
    cfg_path.write_text(cfg_txt, encoding="utf-8")

    cfg_alias = load_yaml(str(cfg_path))
    assert cfg_alias["BUDGET_TOTAL"] == pytest.approx(5.0)
    assert cfg_alias["SP_RATIO"] == pytest.approx(0.6)
    assert cfg_alias["COMBO_RATIO"] == pytest.approx(0.4)
    assert cfg_alias["MAX_VOL_PAR_CHEVAL"] == pytest.approx(0.60)


def test_load_yaml_env_aliases(tmp_path, monkeypatch):
    cfg_path = tmp_path / "gpi.yml"
    cfg_path.write_text(GPI_YML, encoding="utf-8")

    monkeypatch.setenv("TOTAL_BUDGET", "12")
    monkeypatch.setenv("SIMPLE_RATIO", "0.55")
    monkeypatch.setenv("COMBO_SHARE", "0.45")
    monkeypatch.setenv("MAX_STAKE_PER_HORSE", "0.7")
    monkeypatch.setenv("EXOTIC_MIN_PAYOUT", "15")

    cfg_alias = load_yaml(str(cfg_path))
    assert cfg_alias["BUDGET_TOTAL"] == pytest.approx(12.0)
    assert cfg_alias["SP_RATIO"] == pytest.approx(0.6)
    assert cfg_alias["COMBO_RATIO"] == pytest.approx(0.4)
    assert cfg_alias["MAX_VOL_PAR_CHEVAL"] == pytest.approx(0.6)
    assert cfg_alias["MIN_PAYOUT_COMBOS"] == pytest.approx(10.0)
