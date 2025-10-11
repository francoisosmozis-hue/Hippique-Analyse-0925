import json
import shutil
from pathlib import Path

import pytest

from pipeline_run import build_tickets, _cfg_section, _pick_overround_cap


MIN_PARTANTS = 8
MID_ODDS_MIN = 4.0
MID_ODDS_MAX = 7.0


@pytest.fixture(autouse=True)
def cleanup_artifacts():
    artifacts_dir = Path("artifacts")
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)
    yield
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)


def _load_dataset(name: str):
    base = Path("data/ci_sample/race1")
    with base.joinpath(name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_roi_smoke_budget_and_gates():
    h30 = _load_dataset("h30.json")
    h5 = _load_dataset("h5.json")
    assert len(h30) == len(h5) >= MIN_PARTANTS

    sp_odds = [float(runner["odds_win"]) for runner in h5]
    sp_meta = []
    for idx, runner in enumerate(h5):
        sp_meta.append(
            {
                "num": runner["num"],
                "odds": float(runner["odds_win"]),
                "ecurie": f"E{runner['num']}",
                "driver": f"D{runner['num']}",
                "chrono_last": 1.14 + idx * 0.01,
                "j_rate": 0.18 + idx * 0.01,
                "e_rate": 0.12 + idx * 0.01,
            }
        )

    model_probs = [1.4, 0.25, 0.18, 0.12, 0.1, 0.08, 0.05, 0.04]
    market = {
        "sp_odds": sp_odds,
        "sp_meta": sp_meta,
        "model_probs": model_probs,
        "clv_rolling": [-0.05, -0.02, 0.0],
        "expected_payout_combo": 14.0,
    }

    meta = {
        "discipline": "trot",
        "n_partants": len(sp_odds),
        "bankroll": 100.0,
        "todays_returns": [0.0],
        "race_id": "R1C1",
        "clv_rolling": [-0.05, -0.02, 0.0],
        "calibration": {"samples": 80, "ci95_width": 0.2, "abs_err": 0.2, "age_days": 10},
    }

    result = build_tickets(market, budget=5.0, meta=meta)
    tickets = result["tickets"]

    overround = sum(1.0 / odd for odd in sp_odds)
    cap = _pick_overround_cap(meta["discipline"], meta["n_partants"])
    assert overround <= cap

    assert not any(ticket["type"] == "COMBO_AUTO" for ticket in tickets)

    ev_gate = 0.40 * (5.0 * float(_cfg_section("bankroll").get("split_sp", 0.6)))
    if any(MID_ODDS_MIN <= odd <= MID_ODDS_MAX for odd in sp_odds):
        sp_ticket = next((ticket for ticket in tickets if ticket["type"] == "SP_DUTCH"), None)
        assert sp_ticket is not None
        assert sp_ticket["ev"] >= ev_gate - 1e-6

    assert Path("artifacts/metrics.json").exists()
    assert Path("artifacts/per_horse_report.csv").exists()
    assert Path("artifacts/cmd_update_excel.txt").exists()
