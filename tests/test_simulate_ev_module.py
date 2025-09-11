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
    cfg = {
        "BUDGET_TOTAL": 10.0,
        "SP_RATIO": 1.0,
        "MAX_VOL_PAR_CHEVAL": 0.60,
        "KELLY_FRACTION": 0.5,
    }
    runners = [
        {"id": "1", "name": "A", "odds": 2.0, "p": 0.6},
        {"id": "2", "name": "B", "odds": 5.0, "p": 0.3},
    ]
    tickets, ev_sp = allocate_dutching_sp(cfg, runners)
    id_to_p = {r["id"]: r["p"] for r in runners}
    assert all("p" in t for t in tickets)
    for t in tickets:
        assert math.isclose(t["p"], id_to_p[t["id"]])
    total_budget = cfg["BUDGET_TOTAL"] * cfg["SP_RATIO"]
    total_stake = sum(t["stake"] for t in tickets)
    assert math.isclose(total_stake, total_budget * cfg["KELLY_FRACTION"], rel_tol=1e-6)
    assert all(
        t["stake"] <= total_budget * cfg["MAX_VOL_PAR_CHEVAL"] + 1e-6 for t in tickets
    )
    k1 = kelly_fraction(0.6, 2.0 - 1.0)
    k2 = kelly_fraction(0.3, 5.0 - 1.0)
    total_k = k1 + k2
    stake1 = round(
        total_budget * min(cfg["MAX_VOL_PAR_CHEVAL"], k1 * cfg["KELLY_FRACTION"] / total_k),
        2,
    )
    stake2 = round(
        total_budget * min(cfg["MAX_VOL_PAR_CHEVAL"], k2 * cfg["KELLY_FRACTION"] / total_k),
        2,
    )
    expected_ev = stake1 * (0.6 * (2.0 - 1.0) - (1.0 - 0.6)) + stake2 * (
        0.3 * (5.0 - 1.0) - (1.0 - 0.3)
    )
    assert math.isclose(ev_sp, expected_ev)



def test_gate_ev_thresholds():
    cfg = {
        "BUDGET_TOTAL": 100.0,
        "SP_RATIO": 0.5,
        "EV_MIN_SP": 0.2,
        "EV_MIN_GLOBAL": 0.4,
        "ROI_MIN_SP": 0.1,
        "ROI_MIN_GLOBAL": 0.2,
        "MIN_PAYOUT_COMBOS": 10.0,
    }
    res = gate_ev(
        cfg,
        ev_sp=20.0,
        ev_global=50.0,
        roi_sp=0.5,
        roi_global=0.3,
        min_payout_combos=12.0,
    )
    assert res["sp"] and res["combo"]
    res = gate_ev(
        cfg,
        ev_sp=5.0,
        ev_global=30.0,
        roi_sp=0.05,
        roi_global=0.1,
        min_payout_combos=12.0,
        risk_of_ruin=0.01,
    )
    assert not res["sp"]
    assert not res["combo"]
    # Low expected payout should block combined bets even if EV thresholds pass
    res = gate_ev(
        cfg,
        ev_sp=20.0,
        ev_global=50.0,
        roi_sp=0.5,
        roi_global=0.3,
        min_payout_combos=5.0,
        risk_of_ruin=0.01,
    )
    assert res["sp"] and not res["combo"]


def test_simulate_ev_batch_uses_simulate_wrapper():
    tickets = [{"legs": ["a", "b"], "odds": 3.0, "stake": 2.0}]
    res = simulate_ev_batch(tickets, bankroll=10.0)
    # The call should succeed thanks to ``simulate_wrapper`` providing the
    # missing probability.  When the estimated payout is below the minimum
    # threshold, ``compute_ev_roi`` reports the condition in failure reasons.
    assert "expected payout for combined bets" in " ".join(res.get("failure_reasons", []))
    assert "risk_of_ruin" in res
