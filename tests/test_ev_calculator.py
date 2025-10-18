#!/usr/bin/env python3

import math
import os
import sys
from typing import Any, List

import pytest



import inspect

from ev_calculator import compute_ev_roi, risk_of_ruin

SIG = inspect.signature(compute_ev_roi)
EV_THRESHOLD = SIG.parameters["ev_threshold"].default
ROI_THRESHOLD = SIG.parameters["roi_threshold"].default
KELLY_CAP = SIG.parameters["kelly_cap"].default
ROUND_TO = SIG.parameters["round_to"].default


def test_risk_of_ruin_decreases_with_lower_variance() -> None:
    """Risk of ruin should drop as variance decreases for the same EV."""
    ev = 2.0
    bankroll = 100.0
    var_high = 400.0
    var_low = 200.0

    risk_high = risk_of_ruin(ev, var_high, bankroll)
    risk_low = risk_of_ruin(ev, var_low, bankroll)

    assert risk_low < risk_high


def test_risk_of_ruin_respects_baseline_variance() -> None:
    """Baseline variance acts as a conservative floor for ruin risk."""

    ev = 3.0
    bankroll = 80.0
    optimistic_variance = 120.0
    baseline_variance = 240.0

    optimistic_risk = risk_of_ruin(ev, optimistic_variance, bankroll)
    guarded_risk = risk_of_ruin(
        ev,
        optimistic_variance,
        bankroll,
        baseline_variance=baseline_variance,
    )

    baseline_risk = math.exp(-2 * ev * bankroll / baseline_variance)

    assert guarded_risk >= optimistic_risk
    assert guarded_risk == pytest.approx(baseline_risk)


def test_covariance_increases_ror_for_shared_runner() -> None:
    """Tickets sharing the same runner should increase risk via covariance."""

    budget = 100.0
    tickets = [
        {"id": "H1", "p": 0.55, "odds": 2.2, "stake": 10.0},
        {"id": "H1", "p": 0.55, "odds": 3.0, "stake": 5.0},
    ]

    res = compute_ev_roi(tickets, budget=budget, round_to=0)

    assert res["variance"] >= res["variance_naive"]
    assert res["covariance_adjustment"] >= 0.0

    naive_risk = risk_of_ruin(res["ev"], res["variance_naive"], budget)
    assert res["risk_of_ruin"] >= naive_risk


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

    for metrics in res["ticket_metrics"]:
        assert "roi" in metrics
        assert math.isclose(
            metrics["roi"],
            metrics["ev"] / metrics["stake"] if metrics["stake"] else 0.0,
        )
        assert "expected_payout" in metrics
        assert "sharpe" in metrics
    for metrics in res["ticket_metrics_individual"]:
        assert "roi" in metrics
        assert math.isclose(
            metrics["roi"],
            metrics["ev"] / metrics["stake"] if metrics["stake"] else 0.0,
        )
        assert "expected_payout" in metrics
        assert "sharpe" in metrics
    assert "calibrated_expected_payout" in res
    assert "calibrated_expected_payout_individual" in res
    assert math.isclose(res["sharpe"], res["ev_over_std"])


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
            ["expected payout for combined bets ≤ 12€"],
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


def test_variance_cap_triggers_failure() -> None:
    """High variance should trigger a failure reason when capped."""
    tickets = [{"p": 0.5, "odds": 10.0, "stake": 20}]

    res = compute_ev_roi(tickets, budget=100, variance_cap=0.01)

    assert res["green"] is False
    assert "EV ratio below 0.35" in res["failure_reasons"]
