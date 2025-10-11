from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pipeline_run import build_tickets

OVERROUND_TROT_DEFAULT = 1.23
MID_ODDS_MIN = 4.0
MID_ODDS_MAX = 7.0

BASE_DIR = Path(__file__).resolve().parents[1]
CI_SAMPLE_DIR = BASE_DIR / "data" / "ci_sample" / "race1"


@pytest.fixture(scope="module")
def _ci_sample_loaded():
    h30 = json.loads((CI_SAMPLE_DIR / "h30.json").read_text(encoding="utf-8"))
    h5 = json.loads((CI_SAMPLE_DIR / "h5.json").read_text(encoding="utf-8"))
    return h30, h5


def _market_from_sample(h30: list[dict], h5: list[dict]) -> dict:
    odds_h30 = {entry["num"]: float(entry["odds_win_h30"]) for entry in h30}
    odds_h5 = {entry["num"]: float(entry["odds_win_h5"]) for entry in h5}
    nums = sorted(odds_h5.keys(), key=int)
    sp_odds = [odds_h5[num] for num in nums]
    sp_meta = [
        {
            "num": num,
            "odds": odds_h5[num],
            "odds_h30": odds_h30.get(num),
            "ecurie": "E",
            "driver": f"D{num}",
            "chrono_last": 1.14,
        }
        for num in nums
    ]
    return {
        "sp_odds": sp_odds,
        "sp_meta": sp_meta,
        "clv_rolling": [-0.02, -0.01, 0.0, -0.01, 0.0],
        "expected_payout_combo": 20.0,
    }

    
def _overround(odds: list[float]) -> float:
    return sum(1.0 / float(odd) for odd in odds)


def test_roi_smoke_guardrails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _ci_sample_loaded):
    monkeypatch.chdir(tmp_path)
    h30, h5 = _ci_sample_loaded
    market = _market_from_sample(h30, h5)
    meta = {"discipline": "trot", "n_partants": len(market["sp_odds"]), "race_id": "R1C1"}

    result = build_tickets(market, budget=5.0, meta=meta)

    overround_value = _overround(market["sp_odds"])
    assert overround_value <= OVERROUND_TROT_DEFAULT

    tickets = result.get("tickets", [])
    assert all(ticket.get("type") != "COMBO_AUTO" for ticket in tickets)

    artifacts_dir = Path("artifacts")
    metrics_path = artifacts_dir / "metrics.json"
    cmd_path = artifacts_dir / "cmd_update_excel.txt"
    per_horse_path = artifacts_dir / "per_horse_report.csv"

    assert metrics_path.exists()
    assert cmd_path.exists()
    assert per_horse_path.exists()

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert {"overround", "clv_median_30", "kelly_fraction"}.issubset(metrics)

    with per_horse_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert rows, "per_horse_report.csv should list the SP legs"
    assert {"num", "odds_win", "p_no_vig"}.issubset(reader.fieldnames or [])

    sp_tickets = [ticket for ticket in tickets if ticket.get("type") == "SP_DUTCH"]
    if sp_tickets:
        assert any(
            MID_ODDS_MIN <= leg.get("odds", 0.0) <= MID_ODDS_MAX
            for leg in market["sp_meta"]
        )
