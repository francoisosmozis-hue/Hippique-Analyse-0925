import math
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulate_ev import simulate_ev_batch
from validator_ev import validate_ev


def _p_for_ev_ratio(ev_ratio: float) -> float:
    return (math.sqrt(ev_ratio / 0.6) + 1) / 2


def test_ev_ratio_below_threshold_blocked() -> None:
    p = _p_for_ev_ratio(0.35)
    stats = simulate_ev_batch([{"p": p, "odds": 2.0}], bankroll=100)
    assert pytest.approx(stats["ev_ratio"], rel=1e-3) == 0.35
    with pytest.raises(ValueError):
        validate_ev(stats)


def test_ev_ratio_above_threshold_allowed() -> None:
    p = _p_for_ev_ratio(0.55)
    stats = simulate_ev_batch([{"p": p, "odds": 2.0}], bankroll=100)
    assert pytest.approx(stats["ev_ratio"], rel=1e-3) == 0.55
    assert validate_ev(stats) is True

