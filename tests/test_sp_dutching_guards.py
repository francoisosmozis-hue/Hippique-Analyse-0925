from pathlib import Path

import pytest

import pipeline_run
import tickets_builder
from tests.test_pipeline_exotics_filters import (
    _prepare_stubs,
    _write_inputs,
)


def _run_with_sp_ticket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stake: float,
    ev_value: float,
) -> dict:
    eval_stats = {
        "status": "ok",
        "ev_ratio": 0.6,
        "payout_expected": 25.0,
        "roi": 0.3,
        "sharpe": 0.4,
    }

    _prepare_stubs(monkeypatch, eval_stats)

    sp_ticket = {
        "type": "SP",
        "label": "SP",
        "legs": ["1"],
        "stake": stake,
        "ev": ev_value,
    }

    def fake_apply(cfg, runners, combo_candidates=None, combos_source=None, **_kwargs):
        info = {"notes": [], "flags": {"combo": False}, "decision": "reject:no_combo"}
        return [dict(sp_ticket)], [], info

    monkeypatch.setattr(tickets_builder, "apply_ticket_policy", fake_apply)

    roi_value = ev_value / stake if stake else 0.0

    def fake_simulate_with_metrics(tickets, bankroll, kelly_cap=None):
        return {
            "ev": ev_value,
            "roi": roi_value,
            "combined_expected_payout": 20.0,
            "risk_of_ruin": 0.01,
            "ev_over_std": 0.4,
            "variance": 1.0,
        }

    monkeypatch.setattr(pipeline_run, "simulate_with_metrics", fake_simulate_with_metrics)

    inputs = _write_inputs(tmp_path)
    outdir = tmp_path / "out"

    result = pipeline_run.run_pipeline(
        h30=str(inputs["h30"]),
        h5=str(inputs["h5"]),
        stats_je=str(inputs["stats"]),
        partants=str(inputs["partants"]),
        gpi=str(inputs["gpi"]),
        outdir=str(outdir),
        calibration="config/payout_calibration.yaml",
    )
    return result["metrics"]


def test_sp_guard_blocks_low_ev(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = _run_with_sp_ticket(tmp_path, monkeypatch, stake=4.0, ev_value=1.0)

    assert metrics["tickets"]["total"] == 0
    reasons = metrics["abstention_reasons"]
    assert "ev_sp_below_40pct" in reasons
    assert "roi_sp_below_0.20" in reasons
    assert metrics["gates"]["sp"] is False


def test_sp_guard_blocks_stake_over_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Stake above 60% of 5€ budget
    metrics = _run_with_sp_ticket(tmp_path, monkeypatch, stake=3.5, ev_value=2.0)

    reasons = metrics["abstention_reasons"]
    assert "stake_over_cap" in reasons
    assert metrics["tickets"]["total"] == 0


def test_sp_guard_blocks_total_budget_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = _run_with_sp_ticket(tmp_path, monkeypatch, stake=6.0, ev_value=3.0)

    reasons = metrics["abstention_reasons"]
    assert "stake_over_budget" in reasons
    assert metrics["tickets"]["total"] == 0
