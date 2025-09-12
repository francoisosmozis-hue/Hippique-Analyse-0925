import json
import sys
import os

from test_pipeline_smoke import (
    partants_sample,
    odds_h30,
    odds_h5,
    stats_sample,
    GPI_YML,
)
import tickets_builder
import pipeline_run


def test_pipeline_creates_single_combo(tmp_path, monkeypatch):
    # Patch allow_combo to always allow combined bets
    monkeypatch.setattr(tickets_builder, "allow_combo", lambda e, r, p: True)
    monkeypatch.setattr(pipeline_run, "allow_combo", lambda e, r, p: True)
    
    partants = partants_sample()
    h30 = odds_h30()
    h5 = odds_h5()
    stats = stats_sample()

    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats.json"
    partants_path = tmp_path / "partants.json"
    gpi_path = tmp_path / "gpi.yml"
    outdir = tmp_path / "out"

    h30_path.write_text(json.dumps(h30), encoding="utf-8")
    h5_path.write_text(json.dumps(h5), encoding="utf-8")
    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")
    gpi_txt = (
        GPI_YML.replace("EV_MIN_GLOBAL: 0.40", "EV_MIN_GLOBAL: 0.0")
        .replace("EV_MIN_SP: 0.20", "EV_MIN_SP: 0.0")
        + "MIN_PAYOUT_COMBOS: 0.0\nROR_MAX: 1.0\n"
    )
    gpi_path.write_text(gpi_txt, encoding="utf-8")

    diff_path = tmp_path / "diff.json"
    diff_path.write_text("{}", encoding="utf-8")

    argv = [
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
        "0.0",
        "--roi-global",
        "0.0",
        "--max-vol",
        "0.60",
        "--allow-je-na",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    pipeline_run.main()

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    combo_tickets = [t for t in data["tickets"] if t.get("type") == "CP"]
    assert len(combo_tickets) <= 1
    assert combo_tickets, "combo ticket should be created"


def test_pipeline_blocks_combo_on_low_roi(tmp_path, monkeypatch):
    # Patch allow_combo to always allow combined bets so ROI threshold is decisive
    monkeypatch.setattr(tickets_builder, "allow_combo", lambda e, r, p: True)
    monkeypatch.setattr(pipeline_run, "allow_combo", lambda e, r, p: True)

    # Force EV/ROI simulation to return a poor ROI
    monkeypatch.setattr(
        pipeline_run,
        "simulate_ev_batch",
        lambda tickets, bankroll: {
            "ev": 0.0,
            "roi": 0.0,
            "combined_expected_payout": 0.0,
            "risk_of_ruin": 0.0,
        },
    )

    partants = partants_sample()
    h30 = odds_h30()
    h5 = odds_h5()
    stats = stats_sample()

    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats.json"
    partants_path = tmp_path / "partants.json"
    gpi_path = tmp_path / "gpi.yml"
    outdir = tmp_path / "out"

    h30_path.write_text(json.dumps(h30), encoding="utf-8")
    h5_path.write_text(json.dumps(h5), encoding="utf-8")
    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")
    gpi_txt = (
        GPI_YML.replace("EV_MIN_GLOBAL: 0.40", "EV_MIN_GLOBAL: 0.0")
        .replace("EV_MIN_SP: 0.20", "EV_MIN_SP: 0.0")
        + "MIN_PAYOUT_COMBOS: 0.0\nROR_MAX: 1.0\n"
    )
    gpi_path.write_text(gpi_txt, encoding="utf-8")

    diff_path = tmp_path / "diff.json"
    diff_path.write_text("{}", encoding="utf-8")

    argv = [
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
        "0.0",
        "--roi-global",
        "0.5",
        "--max-vol",
        "0.60",
        "--allow-je-na",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    pipeline_run.main()

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    combo_tickets = [t for t in data["tickets"] if t.get("type") == "CP"]
    assert not combo_tickets, "combo ticket should be blocked when ROI too low"


def test_pipeline_abstains_on_low_global_roi(tmp_path, monkeypatch):
    # Patch allow_combo to always allow combined bets and simulate poor ROI
    monkeypatch.setattr(tickets_builder, "allow_combo", lambda e, r, p: True)
    monkeypatch.setattr(pipeline_run, "allow_combo", lambda e, r, p: True)
    monkeypatch.setattr(
        pipeline_run,
        "simulate_ev_batch",
        lambda tickets, bankroll: {
            "ev": 0.0,
            "roi": 0.0,
            "combined_expected_payout": 0.0,
            "risk_of_ruin": 0.0,
        },
    )

    def fake_gate_ev(cfg, ev_sp, ev_global, roi_sp, roi_global, payout, ror, sharpe):
        return {
            "sp": False,
            "combo": False,
            "reasons": {"sp": ["ROI_MIN_GLOBAL"], "combo": ["ROI_MIN_GLOBAL"]},
        }

    monkeypatch.setattr(pipeline_run, "gate_ev", fake_gate_ev)

    partants = partants_sample()
    h30 = odds_h30()
    h5 = odds_h5()
    stats = stats_sample()

    h30_path = tmp_path / "h30.json"
    h5_path = tmp_path / "h5.json"
    stats_path = tmp_path / "stats.json"
    partants_path = tmp_path / "partants.json"
    gpi_path = tmp_path / "gpi.yml"
    outdir = tmp_path / "out"

    h30_path.write_text(json.dumps(h30), encoding="utf-8")
    h5_path.write_text(json.dumps(h5), encoding="utf-8")
    stats_path.write_text(json.dumps(stats), encoding="utf-8")
    partants_path.write_text(json.dumps(partants), encoding="utf-8")
    gpi_txt = (
        GPI_YML.replace("EV_MIN_GLOBAL: 0.40", "EV_MIN_GLOBAL: 0.0")
        .replace("EV_MIN_SP: 0.20", "EV_MIN_SP: 0.0")
        + "MIN_PAYOUT_COMBOS: 0.0\nROR_MAX: 1.0\n"
    )
    gpi_path.write_text(gpi_txt, encoding="utf-8")

    diff_path = tmp_path / "diff.json"
    diff_path.write_text("{}", encoding="utf-8")

    argv = [
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
        "0.0",
        "--roi-global",
        "0.5",
        "--max-vol",
        "0.60",
        "--allow-je-na",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    pipeline_run.main()

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    assert not data["tickets"], "pipeline should abstain when ROI global too low"
