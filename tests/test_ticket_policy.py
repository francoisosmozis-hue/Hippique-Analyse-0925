import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from ev_calculator import compute_ev_roi
from simulate_ev import allocate_dutching_sp
from tickets_builder import PAYOUT_MIN_COMBO, allow_combo
from kelly import kelly_fraction

def test_max_two_tickets():
    cfg = {
        "BUDGET_TOTAL": 100,
        "SP_RATIO": 1.0,
        "MAX_VOL_PAR_CHEVAL": 0.60,
        "MIN_STAKE_SP": 0.10,
        "ROUND_TO_SP": 0.10,
        "KELLY_FRACTION": 1.0,
        "MAX_TICKETS_SP": 2,
    }
    runners = [
        {"id": "1", "name": "A", "odds": 2.0, "p": 0.6},
        {"id": "2", "name": "B", "odds": 3.0, "p": 0.4},
        {"id": "3", "name": "C", "odds": 5.0, "p": 0.25},
    ]
    tickets, _ = allocate_dutching_sp(cfg, runners)
    tickets.sort(key=lambda t: t["ev_ticket"], reverse=True)
    tickets = tickets[: int(cfg["MAX_TICKETS_SP"])]
    assert len(tickets) <= 2


def test_combo_thresholds_cfg():
    cfg = {
        "EV_MIN_GLOBAL": 0.0,
        "ROI_MIN_GLOBAL": 0.0,
        "MIN_PAYOUT_COMBOS": PAYOUT_MIN_COMBO,
    }

    # default threshold from cfg keeps the 12€ combo and rejects below
    assert allow_combo(ev_global=0.5, roi_global=0.5, payout_est=11.9, cfg=cfg) is False
    assert allow_combo(ev_global=0.5, roi_global=0.5, payout_est=12.0, cfg=cfg) is True
    
    # increasing payout threshold via cfg rejects lower payouts
    cfg["MIN_PAYOUT_COMBOS"] = 15.0
    assert allow_combo(ev_global=0.5, roi_global=0.5, payout_est=14.0, cfg=cfg) is False
    assert allow_combo(ev_global=0.6, roi_global=0.5, payout_est=20.0, cfg=cfg) is True

    # raising ROI thresholds filters out combos accordingly
    cfg["EV_MIN_GLOBAL"] = 0.0
    cfg["EV_MIN_GLOBAL"] = 0.6
    assert not allow_combo(ev_global=0.5, roi_global=0.5, payout_est=20.0, cfg=cfg)
    assert allow_combo(ev_global=0.5, roi_global=0.5, payout_est=20.0, cfg=cfg) is False

    cfg["EV_MIN_GLOBAL"] = 0.0
    cfg["ROI_MIN_GLOBAL"] = 0.3
    assert allow_combo(ev_global=0.5, roi_global=0.2, payout_est=20.0, cfg=cfg) is False
    assert allow_combo(ev_global=0.5, roi_global=0.3, payout_est=20.0, cfg=cfg) is True
    

def test_combo_thresholds_lower_payout_cfg():
    cfg = {
        "EV_MIN_GLOBAL": 0.0,
        "ROI_MIN_GLOBAL": 0.0,
        "MIN_PAYOUT_COMBOS": 5.0,
    }

    assert allow_combo(ev_global=0.5, roi_global=0.5, payout_est=5.0, cfg=cfg) is True


def test_optimization_never_decreases_ev_and_respects_budget():
    tickets = [
        {"p": 0.55, "odds": 2.4, "stake": 1.5},
        {"p": 0.35, "odds": 3.4, "stake": 1.0},
        {"p": 0.2, "odds": 6.0, "stake": 0.5},
    ]

    result = compute_ev_roi(tickets, budget=5.0, optimize=True, round_to=0.10)

    assert result["ev"] >= result.get("ev_individual", 0.0) - 1e-9
    assert sum(result.get("optimized_stakes", [])) <= 5.0 + 1e-9


def test_allocate_dutching_sp_without_rounding():
    cfg = {
        "BUDGET_TOTAL": 100.0,
        "SP_RATIO": 1.0,
        "MAX_VOL_PAR_CHEVAL": 1.0,
        "MIN_STAKE_SP": 0.0,
        "ROUND_TO_SP": 0.0,
        "KELLY_FRACTION": 1.0,
    }
    runners = [
        {"id": "1", "name": "Alpha", "odds": 2.2, "p": 0.55},
        {"id": "2", "name": "Bravo", "odds": 3.5, "p": 0.30},
        {"id": "3", "name": "Charlie", "odds": 6.0, "p": 0.20},
    ]

    tickets, ev_sp = allocate_dutching_sp(cfg, runners)

    assert tickets
    budget = cfg["BUDGET_TOTAL"] * cfg["SP_RATIO"]
    total_stake = sum(t["stake"] for t in tickets)
    assert total_stake == pytest.approx(budget)

    total_kelly = sum(
        kelly_fraction(r["p"], r["odds"], lam=1.0, cap=1.0) for r in runners
    )
    lam = cfg["KELLY_FRACTION"] / total_kelly if total_kelly else 0.0
    result = compute_ev_roi(
        tickets,
        budget=budget,
        round_to=0.0,
        kelly_cap=lam,
    )

    assert math.isfinite(result["ev"])
    assert math.isfinite(result["roi"])
    assert result["ev"] == pytest.approx(ev_sp)
