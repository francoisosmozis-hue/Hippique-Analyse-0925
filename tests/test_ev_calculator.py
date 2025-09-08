import math
import os
import sys
from typing import Any, List

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ev_calculator import (
    KELLY_CAP,
    _apply_dutching,
    _kelly_fraction,
    compute_ev_roi,
)


def test_single_bet_ev_positive_and_negative() -> None:
    """Check EV sign for a positive and a negative edge."""
    pos_ticket = [{"p": 0.6, "odds": 2.0, "stake": 10}]
    neg_ticket = [{"p": 0.4, "odds": 2.0, "stake": 10}]

    res_pos = compute_ev_roi(pos_ticket, budget=100)
    res_neg = compute_ev_roi(neg_ticket, budget=100)

    assert res_pos["ev"] > 0
    assert res_neg["ev"] <= 0


def test_dutching_group_equal_profit() -> None:
    """Dutching groups should normalise stakes for identical profit."""
    tickets: List[dict[str, Any]] = [
        {"p": 0.55, "odds": 2.0, "stake": 100, "dutching": "A"},
        {"p": 0.55, "odds": 4.0, "stake": 50, "dutching": "A"},
    ]
    # Large budget so that Kelly capping does not interfere
    compute_ev_roi(tickets, budget=10_000)

    total_stake = sum(t["stake"] for t in tickets)
    profit1 = tickets[0]["stake"] * (tickets[0]["odds"] - 1)
    profit2 = tickets[1]["stake"] * (tickets[1]["odds"] - 1)

    assert math.isclose(total_stake, 150)
    assert math.isclose(profit1, profit2)


def test_combined_bet_with_simulator() -> None:
    """Combined bets rely on the provided simulation function for probability."""
    called: List[List[Any]] = []

    def fake_simulator(legs: List[Any]) -> float:  # pragma: no cover - simple stub
        called.append(legs)
        assert legs == ["leg1", "leg2"]
        return 0.25

    tickets = [{"odds": 10.0, "stake": 10, "legs": ["leg1", "leg2"]}]
    res = compute_ev_roi(tickets, budget=1_000, simulate_fn=fake_simulator)

    assert called == [["leg1", "leg2"]]
    assert math.isclose(res["ev"], 15.0)
    assert math.isclose(res["roi"], 1.5)


def test_kelly_cap_respected() -> None:
    """Stake must be capped to 60% of the Kelly recommendation."""
    p, odds = 0.6, 2.0
    budget = 1_000
    tickets = [{"p": p, "odds": odds, "stake": 1_000}]
    res = compute_ev_roi(tickets, budget=budget)

    kelly_fraction = (p * odds - 1) / (odds - 1)
    kelly_stake = kelly_fraction * budget
    expected_stake = kelly_stake * KELLY_CAP
    expected_ev = expected_stake * (p * (odds - 1) - (1 - p))

    assert math.isclose(res["ev"], expected_ev)
    # Derive the actual stake used from EV
    actual_stake = res["ev"] / (p * (odds - 1) - (1 - p))
    assert math.isclose(actual_stake, expected_stake)


def test_invalid_probability_raises() -> None:
    """Probabilities must be strictly between 0 and 1."""
    with pytest.raises(ValueError):
        _kelly_fraction(0.0, 2.0)
    with pytest.raises(ValueError):
        compute_ev_roi([{"p": 1.5, "odds": 2.0}], budget=100)


def test_invalid_odds_raises() -> None:
    """Odds must be greater than 1."""
    with pytest.raises(ValueError):
        _kelly_fraction(0.5, 1.0)
    with pytest.raises(ValueError):
        compute_ev_roi([{"p": 0.5, "odds": 1.0}], budget=100)


def test_apply_dutching_ignores_invalid_odds() -> None:
    """Tickets with odds <= 1 are ignored during dutching."""
    tickets = [
        {"p": 0.5, "odds": 1.0, "stake": 100, "dutching": "A"},
        {"p": 0.5, "odds": 2.0, "stake": 50, "dutching": "A"},
    ]

    _apply_dutching(tickets)

    assert tickets[0]["stake"] == 100
    assert tickets[1]["stake"] == 50

