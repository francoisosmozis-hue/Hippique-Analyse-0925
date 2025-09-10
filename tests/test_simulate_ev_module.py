import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulate_ev import (
    implied_probs,
    kelly_fraction,
    allocate_dutching_sp,
    gate_ev,
    simulate_ev_batch,
)


def test_implied_probs_normalizes():
    probs = implied_probs([2.0, 4.0])
    assert len(probs) == 2
    assert math.isclose(sum(probs), 1.0)
    expected = (1 / 2) / ((1 / 2) + (1 / 4))
    assert math.isclose(probs[0], expected)


def test_kelly_fraction_basic():
    assert math.isclose(kelly_fraction(0.6, 1.0), 0.2)
    assert math.isclose(kelly_fraction(0.2, 1.0), 0.0)


def test_allocate_dutching_sp_cap():
    cfg = {"BUDGET_TOTAL": 10.0, "SP_RATIO": 1.0, "MAX_VOL_PAR_CHEVAL": 0.60}
    runners = [
        {"id": "1", "name": "A", "odds": 2.0},
        {"id": "2", "name": "B", "odds": 5.0},
    ]
    tickets, ev_sp = allocate_dutching_sp(cfg, runners)
    total_budget = cfg["BUDGET_TOTAL"] * cfg["SP_RATIO"]
    assert sum(t["stake"] for t in tickets) <= total_budget + 1e-6
    assert all(t["stake"] <= total_budget * cfg["MAX_VOL_PAR_CHEVAL"] + 1e-6 for t in tickets)
    assert ev_sp != 0


def test_gate_ev_thresholds():
    cfg = {
        "BUDGET_TOTAL": 100.0,
        "SP_RATIO": 0.5,
        "EV_MIN_SP": 0.2,
        "EV_MIN_GLOBAL": 0.4,
        "MIN_PAYOUT_COMBOS": 10.0,
    }
    res = gate_ev(cfg, ev_sp=20.0, ev_global=50.0, min_payout_combos=12.0)
    assert res["sp"] and res["combo"]
    res = gate_ev(cfg, ev_sp=5.0, ev_global=30.0, min_payout_combos=12.0)
    assert not res["sp"]
    assert not res["combo"]


def test_simulate_ev_batch_uses_simulate_wrapper():
    tickets = [{"legs": ["a", "b"], "odds": 3.0, "stake": 2.0}]
    res = simulate_ev_batch(tickets, bankroll=10.0)
    # The call should succeed thanks to ``simulate_wrapper`` providing the
    # missing probability.  When the estimated payout is below the minimum
    # threshold, ``compute_ev_roi`` reports the condition in failure reasons.
    assert "expected payout for combined bets" in " ".join(res.get("failure_reasons", []))
