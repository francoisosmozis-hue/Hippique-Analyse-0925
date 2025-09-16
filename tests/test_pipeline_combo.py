import json
import sys

import pytest

import pipeline_run
import tickets_builder
from test_pipeline_smoke import (
    GPI_YML,
    odds_h30,
    odds_h5,
    partants_sample,
    stats_sample,    
)


def _with_exotics(partants: dict) -> dict:
    combos = {
        "CP": [
            {"id": "cp-alpha", "legs": ["1", "2"], "odds": 6.0, "stake": 1.0},
        ],
        "TRIO": [
            {"id": "trio-beta", "legs": ["1", "2", "3"], "odds": 15.0, "stake": 1.0},
        ],
    }
    enriched = dict(partants)
    enriched["exotics"] = combos
    return enriched

def _write_inputs(tmp_path, partants):
    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats.json"
    partants_path = tmp_path / "partants.json"
    gpi_path = tmp_path / "gpi.yml"
    diff_path = tmp_path / "diff.json"

    h30_path.write_text(json.dumps(odds_h30()), encoding="utf-8")
    h5_path.write_text(json.dumps(odds_h5()), encoding="utf-8")
    stats_path.write_text(json.dumps(stats_sample()), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")
    
    gpi_txt = (
        GPI_YML
        .replace("EV_MIN_GLOBAL: 0.40", "EV_MIN_GLOBAL: 0.0")
        .replace("EV_MIN_SP: 0.20", "EV_MIN_SP: 0.0")
        + "MIN_PAYOUT_COMBOS: 0.0\nROR_MAX: 1.0\n"
    )
    gpi_path.write_text(gpi_txt, encoding="utf-8")
    diff_path.write_text("{}", encoding="utf-8")

    return {
        "h30": h30_path,
        "h5": h5_path,
        "stats": stats_path,
        "partants": partants_path,
        "gpi": gpi_path,
        "diff": diff_path,
    }


def _run_pipeline(tmp_path, inputs):
    outdir = tmp_path / "out"
    argv = [
        "pipeline_run.py",
        "analyse",
        "--h30",
        str(inputs["h30"]),
        "--h5",
        str(inputs["h5"]),
        "--stats-je",
        str(stats_path),
        "--partants",
        str(inputs["partants"]),
        "--gpi",
        str(inputs["gpi"]),
        "--outdir",
        str(outdir),
        "--diff",
        str(inputs["diff"]),
        "--budget",
        "5",
        "--ev-global",
        "0.0",
        "--roi-global",
        "0.0",
        "--max-vol",
        "0.60",
        "--allow-je-na",
    ]
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sys, "argv", argv)
    try:
        pipeline_run.main()
    finally:
        monkeypatch.undo()
    return outdir


def test_pipeline_allocates_combo_budget(tmp_path, monkeypatch):
    partants = _with_exotics(partants_sample())
    inputs = _write_inputs(tmp_path, partants)

    def fake_validate(candidates, bankroll, **kwargs):
        validated = []
        for idx, candidate in enumerate(candidates, start=1):
            ticket = candidate[0]
            validated.append(
                {
                    "id": f"{ticket['type']}{idx}",
                    "type": ticket["type"],
                    "legs": ticket["legs"],
                    "ev_check": {
                        "ev_ratio": 0.5,
                        "roi": 0.5,
                        "payout_expected": 40.0,
                    },
                }
            )
        return validated, {"notes": [], "flags": {"combo": True}}

    monkeypatch.setattr(tickets_builder, "validate_exotics_with_simwrapper", fake_validate)
    monkeypatch.setattr(pipeline_run, "allow_combo", lambda *args, **kwargs: True)

    calls = []

    def fake_simulate(tickets, bankroll):
        calls.append([dict(t) for t in tickets])
        total = sum(t.get("stake", 0.0) for t in tickets)
        return {
            "ev": total * 0.2,
            "roi": 0.2,
            "combined_expected_payout": total * 3.0,
            "risk_of_ruin": 0.1,
            "ev_over_std": 0.5,
            "variance": 1.2,
            "clv": 0.0,
        }

    monkeypatch.setattr(pipeline_run, "simulate_ev_batch", fake_simulate)
    monkeypatch.setattr(
        pipeline_run,
        "gate_ev",
        lambda *args, **kwargs: {"sp": True, "combo": True, "reasons": {"sp": [], "combo": []}},
    )
    outdir = _run_pipeline(tmp_path, inputs)

    assert calls, "simulate_ev_batch should be called"
    final_call = calls[-1]
    combo_stakes = [t["stake"] for t in final_call if t.get("type") in {"CP", "TRIO", "ZE4"}]
    assert len(combo_stakes) == 2
    combo_budget = 5 * 0.4
    assert sum(combo_stakes) == pytest.approx(combo_budget)
    assert all(stake == pytest.approx(combo_budget / 2) for stake in combo_stakes)

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    combo_ids = [t["id"] for t in data["tickets"] if t.get("type") in {"CP", "TRIO"}]
    assert combo_ids and {"CP1", "TRIO2"}.issuperset(combo_ids)
    assert data["ev"]["global"] == pytest.approx(sum(t["stake"] for t in final_call) * 0.2)
    assert data["ev"]["variance"] == pytest.approx(1.2)
    assert data["ev"]["combined_expected_payout"] == pytest.approx(sum(t["stake"] for t in final_call) * 3.0)


def test_pipeline_recomputes_after_combo_rejection(tmp_path, monkeypatch):
    partants = _with_exotics(partants_sample())
    inputs = _write_inputs(tmp_path, partants)

    def fake_validate(candidates, bankroll, **kwargs):
        validated = []
        for idx, candidate in enumerate(candidates, start=1):
            ticket = candidate[0]
            validated.append(
                {
                    "id": f"{ticket['type']}{idx}",
                    "type": ticket["type"],
                    "legs": ticket["legs"],
                    "ev_check": {
                        "ev_ratio": 0.5,
                        "roi": 0.5,
                        "payout_expected": 40.0,
                    },
                }
            )
        return validated, {"notes": [], "flags": {"combo": True}}

    monkeypatch.setattr(tickets_builder, "validate_exotics_with_simwrapper", fake_validate)
    monkeypatch.setattr(pipeline_run, "allow_combo", lambda *args, **kwargs: True)

    calls = []

    def fake_simulate(tickets, bankroll):
        calls.append([dict(t) for t in tickets])
        total = sum(t.get("stake", 0.0) for t in tickets)
        return {
            "ev": total * 0.1,
            "roi": 0.1,
            "combined_expected_payout": total * 2.0,
            "risk_of_ruin": 0.05,
            "ev_over_std": 0.4,
            "variance": 0.8,
            "clv": 0.0,

    monkeypatch.setattr(pipeline_run, "simulate_ev_batch", fake_simulate)
    def fake_gate(cfg, *args, **kwargs):
        return {"sp": True, "combo": False, "reasons": {"sp": [], "combo": ["ROI_MIN_GLOBAL"]}}

    monkeypatch.setattr(pipeline_run, "gate_ev", fake_gate)

    outdir = _run_pipeline(tmp_path, inputs)

    assert calls, "simulate_ev_batch should be called at least once"
    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    combo_tickets = [t for t in data["tickets"] if t.get("type") != "SP"]
    assert not combo_tickets
    final_total = sum(t.get("stake", 0.0) for t in data["tickets"])
    assert data["ev"]["global"] == pytest.approx(final_total * 0.1)
    assert data["ev"]["combined_expected_payout"] == pytest.approx(final_total * 2.0)
