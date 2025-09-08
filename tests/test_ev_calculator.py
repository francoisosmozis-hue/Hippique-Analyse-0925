#!/usr/bin/env python3

import math
import os
import sys
from typing import Any, List

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ev_calculator import (
    _apply_dutching,
    _kelly_fraction,
    compute_ev_roi,
    risk_of_ruin,
)
import inspect

SIG = inspect.signature(compute_ev_roi)
EV_THRESHOLD = SIG.parameters["ev_threshold"].default
ROI_THRESHOLD = SIG.parameters["roi_threshold"].default
KELLY_CAP = SIG.parameters["kelly_cap"].default


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


def test_simulate_fn_called_once_for_identical_legs() -> None:
    """Repeated combined bets with same legs should reuse cached probability."""
    call_count = 0

    def fake_simulator(legs: List[Any]) -> float:  # pragma: no cover - simple stub
        nonlocal call_count
        call_count += 1
        return 0.3

    shared_legs = ["A", "B"]
    tickets = [
        {"odds": 3.0, "legs": shared_legs},
        {"odds": 5.0, "legs": shared_legs},
    ]

    compute_ev_roi(tickets, budget=100, simulate_fn=fake_simulator)

    assert call_count == 1


def test_kelly_cap_respected() -> None:
    """Stake must be capped to 60% of the Kelly recommendation."""
    p, odds = 0.6, 2.0
    budget = 1_000
    tickets = [{"p": p, "odds": odds, "stake": 1_000}]
    res = compute_ev_roi(tickets, budget=budget, kelly_cap=KELLY_CAP)

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


def test_budget_must_be_positive() -> None:
    """Budget must be greater than 0."""
    with pytest.raises(ValueError):
        compute_ev_roi([{"p": 0.5, "odds": 2.0}], budget=0)
    with pytest.raises(ValueError):
        compute_ev_roi([{"p": 0.5, "odds": 2.0}], budget=-1)


def test_apply_dutching_ignores_invalid_odds() -> None:
    """Tickets with odds <= 1 are ignored during dutching."""
    tickets = [
        {"p": 0.5, "odds": 1.0, "stake": 100, "dutching": "A"},
        {"p": 0.5, "odds": 2.0, "stake": 50, "dutching": "A"},
    ]

    _apply_dutching(tickets)

    assert tickets[0]["stake"] == 100
    assert tickets[1]["stake"] == 50


def test_stakes_normalized_when_exceeding_budget() -> None:
    """Stakes are proportionally reduced when exceeding the budget."""
    budget = 100
    tickets = [
        {"p": 0.99, "odds": 2.0},
        {"p": 0.9, "odds": 5.0},
    ]

    k1 = _kelly_fraction(0.99, 2.0) * budget * KELLY_CAP
    k2 = _kelly_fraction(0.9, 5.0) * budget * KELLY_CAP
    total = k1 + k2
    scale = budget / total

    expected1 = k1 * scale
    expected2 = k2 * scale

    res = compute_ev_roi(tickets, budget=budget, kelly_cap=KELLY_CAP)


    assert math.isclose(sum(t["stake"] for t in tickets), budget)
    assert math.isclose(tickets[0]["stake"], expected1)
    assert math.isclose(tickets[1]["stake"], expected2)
    assert math.isclose(res["total_stake_normalized"], budget)


def test_ticket_metrics_and_std_dev() -> None:
    """Ticket metrics and aggregated statistics should be reported."""
    tickets = [
        {"p": 0.6, "odds": 2.0, "closing_odds": 2.1},
        {"p": 0.4, "odds": 3.0, "closing_odds": 3.2},
    ]

    res = compute_ev_roi(tickets, budget=100)
    metrics = res["ticket_metrics"]

    assert len(metrics) == 2

    k1 = _kelly_fraction(0.6, 2.0) * 100
    s1 = min(k1, k1 * KELLY_CAP)
    ev1 = s1 * (0.6 * (2.0 - 1) - (1 - 0.6))
    var1 = 0.6 * 0.4 * (s1 * 2.0) ** 2
    clv1 = (2.1 - 2.0) / 2.0
    assert math.isclose(metrics[0]["kelly_stake"], k1)
    assert math.isclose(metrics[0]["stake"], s1)
    assert math.isclose(metrics[0]["ev"], ev1)
    assert math.isclose(metrics[0]["variance"], var1)
    assert math.isclose(metrics[0]["clv"], clv1)

    k2 = _kelly_fraction(0.4, 3.0) * 100
    s2 = min(k2, k2 * KELLY_CAP)
    ev2 = s2 * (0.4 * (3.0 - 1) - (1 - 0.4))
    var2 = 0.4 * 0.6 * (s2 * 3.0) ** 2
    clv2 = (3.2 - 3.0) / 3.0
    assert math.isclose(metrics[1]["kelly_stake"], k2)
    assert math.isclose(metrics[1]["stake"], s2)
    assert math.isclose(metrics[1]["ev"], ev2)
    assert math.isclose(metrics[1]["variance"], var2)
    assert math.isclose(metrics[1]["clv"], clv2)

    expected_std = math.sqrt(var1 + var2)
    expected_ratio = (ev1 + ev2) / expected_std
    assert math.isclose(res["std_dev"], expected_std)
    assert math.isclose(res["ev_over_std"], expected_ratio)


def test_average_clv_from_closing_odds() -> None:
    """Providing closing odds should compute CLV per ticket and overall."""
    tickets = [
        {"p": 0.5, "odds": 2.0, "closing_odds": 2.2},
        {"p": 0.5, "odds": 3.0, "closing_odds": 3.3},
    ]

    res = compute_ev_roi(tickets, budget=100)

    clv1 = (2.2 - 2.0) / 2.0
    clv2 = (3.3 - 3.0) / 3.0
    assert math.isclose(tickets[0]["clv"], clv1)
    assert math.isclose(tickets[1]["clv"], clv2)
    assert math.isclose(res["clv"], (clv1 + clv2) / 2)


def test_risk_of_ruin_decreases_with_lower_variance() -> None:
    """Risk of ruin should drop as variance decreases for the same EV."""
    ev = 2.0
    bankroll = 100.0
    var_high = 400.0
    var_low = 200.0

    risk_high = risk_of_ruin(ev, var_high, bankroll)
    risk_low = risk_of_ruin(ev, var_low, bankroll)

    assert risk_low < risk_high


def test_optimized_allocation_respects_budget_and_improves_ev() -> None:
    """Optimisation should keep stakes within budget and increase EV."""
    tickets = [
        {"p": 0.9, "odds": 2.0},
        {"p": 0.8, "odds": 3.0},
        {"p": 0.7, "odds": 3.0},
    ]

    res = compute_ev_roi(tickets, budget=100, optimize=True)

    assert sum(res["optimized_stakes"]) <= 100 + 1e-6
    assert res["ev"] > res["ev_individual"]



def test_green_flag_true_when_thresholds_met() -> None:
    """EV ratio and ROI above thresholds should yield a green flag."""
    tickets = [{"p": 0.8, "odds": 2.5}]

    res = compute_ev_roi(
        tickets,
        budget=100,
        ev_threshold=EV_THRESHOLD,
        roi_threshold=ROI_THRESHOLD,
    )

    assert res["ev_ratio"] >= EV_THRESHOLD
    assert res["roi"] >= ROI_THRESHOLD
    assert res["green"] is True
    assert "failure_reasons" not in res


@pytest.mark.parametrize(
    "tickets,budget,expected_reasons",
    [
        ([{"p": 0.65, "odds": 2.0}], 100, [f"EV ratio below {EV_THRESHOLD:.2f}"]),
        (
            [{"p": 0.55, "odds": 2.0}],
            100,
            [
                f"EV ratio below {EV_THRESHOLD:.2f}",
                f"ROI below {ROI_THRESHOLD:.2f}",
            ],
        ),
        (
            [{"p": 0.8, "odds": 2.5, "legs": ["leg1", "leg2"]}],
            10,
            ["expected payout for combined bets ≤ 10€"],
        ),
    ],
)
def test_green_flag_failure_reasons(
    tickets: List[dict[str, Any]], budget: float, expected_reasons: List[str]
) -> None:
    """Check that failing criteria produce the appropriate reasons."""
    res = compute_ev_roi(
        tickets,
        budget=budget,
        ev_threshold=EV_THRESHOLD,
        roi_threshold=ROI_THRESHOLD,
    )

    assert res["green"] is False
    assert res["failure_reasons"] == expected_reasons

