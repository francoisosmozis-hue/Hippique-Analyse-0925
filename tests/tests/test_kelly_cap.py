import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ev_calculator import compute_ev_roi


def test_kelly_cap_limits_stakes():
    tickets = [{"p": 0.99, "odds": 2.0}]
    budget = 100.0
    compute_ev_roi(tickets, budget=budget, kelly_cap=0.60, round_to=0)
    assert tickets[0]["stake"] <= 0.60 * budget
