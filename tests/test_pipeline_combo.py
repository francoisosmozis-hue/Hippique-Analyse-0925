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
    monkeypatch.setattr(tickets_builder, "allow_combo", lambda e, p: True)
    monkeypatch.setattr(pipeline_run, "allow_combo", lambda e, p: True)

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

    argv = [
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
    monkeypatch.setattr(sys, "argv", argv)
    pipeline_run.main()

    data = json.loads((outdir / "p_finale.json").read_text(encoding="utf-8"))
    combo_tickets = [t for t in data["tickets"] if t.get("type") == "CP"]
    assert len(combo_tickets) <= 1
    assert combo_tickets, "combo ticket should be created"
