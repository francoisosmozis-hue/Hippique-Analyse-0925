import os
import sys

import pytest



from ev_calculator import compute_ev_roi
from validator_ev import ValidationError, validate_budget


def test_kelly_cap_limits_stakes():
    tickets = [{"p": 0.99, "odds": 2.0}]
    budget = 100.0
    compute_ev_roi(tickets, budget=budget, kelly_cap=0.60, round_to=0)
    assert tickets[0]["stake"] <= 0.60 * budget


def test_validate_budget_ok():
    stakes = {"horse1": 40.0, "horse2": 20.0}
    assert validate_budget(stakes, budget_cap=100.0, max_vol_per_horse=0.60)


def test_validate_budget_total_exceeded():
    stakes = {"h1": 80.0, "h2": 30.0}
    with pytest.raises(ValidationError):
        validate_budget(stakes, budget_cap=100.0, max_vol_per_horse=0.60)


def test_validate_budget_horse_cap_exceeded():
    stakes = {"h1": 70.0, "h2": 20.0}
    with pytest.raises(ValidationError):
        validate_budget(stakes, budget_cap=100.0, max_vol_per_horse=0.60)
