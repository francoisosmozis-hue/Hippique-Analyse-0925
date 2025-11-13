import math
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kelly import kelly_fraction
from simulate_ev import (
    allocate_dutching_sp,
    gate_ev,
    implied_probs,
    normalize_overround,
    simulate_ev_batch,
)


def test_implied_probs_normalizes():
    probs = implied_probs([2.0, 4.0])
    assert len(probs) == 2
    assert math.isclose(sum(probs), 1.0)
    expected = (1 / 2) / ((1 / 2) + (1 / 4))
    assert math.isclose(probs[0], expected)


def test_normalize_overround_balances_dict():
    raw = {"1": 0.6, "2": 0.9, "3": 0.3}
    normalised = normalize_overround(raw)
    assert math.isclose(sum(normalised.values()), 1.0)
    assert all(value >= 0.0 for value in normalised.values())


def test_kelly_fraction_basic():
    assert math.isclose(kelly_fraction(0.6, 2.0, lam=1.0), 0.2)
    assert math.isclose(kelly_fraction(0.2, 2.0, lam=1.0), 0.0)


def test_allocate_dutching_sp_cap():
    cfg = {
        "BUDGET_TOTAL": 10.0,
        "SP_RATIO": 1.0,
        "MAX_VOL_PAR_CHEVAL": 0.60,
        "KELLY_FRACTION": 0.5,
        "MIN_STAKE_SP": 0.1,
        "ROUND_TO_SP": 0.1,
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
    step = cfg["ROUND_TO_SP"]
    assert all(
        math.isclose(round(t["stake"] / step) * step, t["stake"], abs_tol=1e-9)
        for t in tickets
    )
    total_budget = cfg["BUDGET_TOTAL"] * cfg["SP_RATIO"]
    total_stake = sum(t["stake"] for t in tickets)
    target = total_budget * cfg["KELLY_FRACTION"]
    assert abs(total_stake - target) <= step / 2
    assert all(
        t["stake"] <= total_budget * cfg["MAX_VOL_PAR_CHEVAL"] + 1e-6 for t in tickets
    )
    expected_ev = sum(
        t["stake"] * (t["p"] * (t["odds"] - 1.0) - (1.0 - t["p"])) for t in tickets
    )
    assert math.isclose(ev_sp, expected_ev)


def test_allocate_dutching_sp_min_stake_filter():
    cfg = {
        "BUDGET_TOTAL": 0.49,
        "SP_RATIO": 1.0,
        "MAX_VOL_PAR_CHEVAL": 0.60,
        "KELLY_FRACTION": 0.5,
        "MIN_STAKE_SP": 0.1,
        "ROUND_TO_SP": 0.1,
    }
    runners = [
        {"id": "1", "name": "A", "odds": 2.0, "p": 0.6},
        {"id": "2", "name": "B", "odds": 5.0, "p": 0.3},
    ]
    tickets, ev_sp = allocate_dutching_sp(cfg, runners)
    assert len(tickets) == 1
    assert tickets[0]["id"] == "1"
    assert tickets[0]["stake"] >= cfg["MIN_STAKE_SP"]
    step = cfg["ROUND_TO_SP"]
    assert math.isclose(
        round(tickets[0]["stake"] / step) * step, tickets[0]["stake"], abs_tol=1e-9
    )
    expected_ev = tickets[0]["stake"] * (0.6 * (2.0 - 1.0) - (1.0 - 0.6))
    assert math.isclose(ev_sp, expected_ev)
    total_budget = cfg["BUDGET_TOTAL"] * cfg["SP_RATIO"]
    target = total_budget * cfg["KELLY_FRACTION"]
    total_stake = sum(t["stake"] for t in tickets)
    assert abs(total_stake - target) <= step / 2



def test_allocate_dutching_sp_skips_invalid():
    cfg = {
        "BUDGET_TOTAL": 10.0,
        "SP_RATIO": 1.0,
        "MAX_VOL_PAR_CHEVAL": 0.60,
        "KELLY_FRACTION": 0.5,
        "MIN_STAKE_SP": 0.1,
        "ROUND_TO_SP": 0.1,
    }
    runners = [
        {"id": "1", "name": "A", "odds": 2.0, "p": 0.6},
        {"id": "2", "name": "B", "odds": 1.0, "p": 0.3},  # invalid odds
        {"id": "3", "name": "C", "odds": 5.0, "p": 1.2},  # invalid probability
    ]
    tickets, ev_sp = allocate_dutching_sp(cfg, runners)
    assert [t["id"] for t in tickets] == ["1"]
    expected_ev = tickets[0]["stake"] * (0.6 * (2.0 - 1.0) - (1.0 - 0.6))
    assert math.isclose(ev_sp, expected_ev)


def test_allocate_dutching_sp_uses_precomputed_implied_probs():
    cfg = {
        "BUDGET_TOTAL": 10.0,
        "SP_RATIO": 1.0,
        "MAX_VOL_PAR_CHEVAL": 0.60,
        "KELLY_FRACTION": 0.5,
        "MIN_STAKE_SP": 0.1,
        "ROUND_TO_SP": 0.1,
    }
    runners = [
        {"id": "1", "name": "A", "odds": 2.0, "p_imp_h5": 0.6},
        {"id": "2", "name": "B", "odds": 5.0, "p_imp_h5": 0.4},
    ]
    tickets, _ = allocate_dutching_sp(cfg, runners)
    assert {t["id"] for t in tickets} == {"1", "2"}
    p_by_id = {t["id"]: t["p"] for t in tickets}
    assert p_by_id["1"] == pytest.approx(0.6)
    assert p_by_id["2"] == pytest.approx(0.4)


def test_allocate_dutching_sp_fallbacks_when_probabilities_invalid():
    cfg = {
        "BUDGET_TOTAL": 10.0,
        "SP_RATIO": 1.0,
        "MAX_VOL_PAR_CHEVAL": 0.60,
        "KELLY_FRACTION": 0.5,
        "MIN_STAKE_SP": 0.1,
        "ROUND_TO_SP": 0.1,
    }
    runners = [
        {"id": "1", "name": "A", "odds": 2.0, "p_imp_h5": 0.0},
        {"id": "2", "name": "B", "odds": 4.0, "p_imp_h5": -1.0},
    ]
    tickets, _ = allocate_dutching_sp(cfg, runners)
    probs = implied_probs([2.0, 4.0])
    p_by_id = {t["id"]: t["p"] for t in tickets}
    assert p_by_id["1"] == pytest.approx(probs[0])
    assert p_by_id["2"] == pytest.approx(probs[1])


def test_gate_ev_thresholds():
    cfg = {
        "BUDGET_TOTAL": 100.0,
        "SP_RATIO": 0.5,
        "EV_MIN_SP": 0.15,
        "EV_MIN_GLOBAL": 0.35,
        "ROI_MIN_SP": 0.1,
        "ROI_MIN_GLOBAL": 0.25,
        "MIN_PAYOUT_COMBOS": 12.0,
    }
    res = gate_ev(
        cfg,
        ev_sp=20.0,
        ev_global=50.0,
        roi_sp=0.5,
        roi_global=0.3,
        min_payout_combos=12.0,
        ev_over_std=1.0,
    )
    assert res["sp"] and res["combo"]
    assert res["reasons"] == {"sp": [], "combo": []}

    res = gate_ev(
        cfg,
        ev_sp=5.0,
        ev_global=30.0,
        roi_sp=0.05,
        roi_global=0.1,
        min_payout_combos=12.0,
        risk_of_ruin=0.01,
        ev_over_std=1.0,
    )
    assert not res["sp"]
    assert not res["combo"]
    assert set(res["reasons"]["sp"]) == {"EV_MIN_SP", "ROI_MIN_SP"}
    assert set(res["reasons"]["combo"]) == {"EV_MIN_GLOBAL", "ROI_MIN_GLOBAL"}
    # Low expected payout should block combined bets even if EV thresholds pass
    res = gate_ev(
        cfg,
        ev_sp=20.0,
        ev_global=50.0,
        roi_sp=0.5,
        roi_global=0.3,
        min_payout_combos=6.0,
        risk_of_ruin=0.01,
        ev_over_std=1.0,
    )
    assert res["sp"] and not res["combo"]
    assert res["reasons"]["sp"] == []
    assert res["reasons"]["combo"] == ["MIN_PAYOUT_COMBOS"]

    cfg_homo = dict(cfg)
    cfg_homo["EV_MIN_SP_HOMOGENEOUS"] = 0.05
    res = gate_ev(
        cfg_homo,
        ev_sp=4.0,
        ev_global=50.0,
        roi_sp=0.2,
        roi_global=0.3,
        min_payout_combos=20.0,
        ev_over_std=1.0,
        homogeneous_field=True,
    )
    assert res["sp"] and res["combo"]
    assert res["reasons"] == {"sp": [], "combo": []}

    # Exceeding risk of ruin should block both types and record ROR_MAX
    cfg_ror = {
        "BUDGET_TOTAL": 100.0,
        "SP_RATIO": 0.5,
        "EV_MIN_SP": 0.0,
        "EV_MIN_GLOBAL": 0.0,
        "ROI_MIN_SP": 0.0,
        "ROI_MIN_GLOBAL": 0.0,
        "MIN_PAYOUT_COMBOS": 0.0,
        "ROR_MAX": 0.05,
    }
    res = gate_ev(
        cfg_ror,
        ev_sp=0.0,
        ev_global=0.0,
        roi_sp=0.0,
        roi_global=0.0,
        min_payout_combos=0.0,
        risk_of_ruin=0.1,
        ev_over_std=1.0,
    )
    assert not res["sp"] and not res["combo"]
    assert res["reasons"]["sp"] == ["ROR_MAX"]
    assert res["reasons"]["combo"] == ["ROR_MAX"]

def test_gate_ev_sharpe_min():
    cfg = {
        "BUDGET_TOTAL": 100.0,
        "SP_RATIO": 0.5,
        "EV_MIN_SP": 0.0,
        "EV_MIN_GLOBAL": 0.0,
        "ROI_MIN_SP": 0.0,
        "ROI_MIN_GLOBAL": 0.0,
        "MIN_PAYOUT_COMBOS": 0.0,
        "SHARPE_MIN": 0.5,
    }
    res = gate_ev(
        cfg,
        ev_sp=50.0,
        ev_global=100.0,
        roi_sp=0.5,
        roi_global=0.5,
        min_payout_combos=20.0,
        ev_over_std=0.3,
    )
    assert not res["sp"] and not res["combo"]
    assert res["reasons"]["sp"] == ["SHARPE_MIN"]
    assert res["reasons"]["combo"] == ["SHARPE_MIN"]
def test_simulate_ev_batch_uses_simulate_wrapper():
    tickets = [{"legs": ["a", "b"], "odds": 3.0, "stake": 2.0}]
    res = simulate_ev_batch(tickets, bankroll=10.0)
    # The call should succeed thanks to ``simulate_wrapper`` providing the
    # missing probability.  When the estimated payout is below the minimum
    # threshold, ``compute_ev_roi`` reports the condition in failure reasons.
    assert "expected payout for combined bets" in " ".join(res.get("failure_reasons", []))
    assert "risk_of_ruin" in res
    assert math.isclose(res.get("sharpe", 0.0), res.get("ev_over_std", 0.0))
    assert res.get("calibrated_expected_payout", 0.0) >= 0.0
    assert all("expected_payout" in t for t in tickets)
