#!/usr/bin/env python3
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulate_wrapper import simulate_wrapper


def test_beta_binomial_fallback() -> None:
    """Missing combinations use a Beta-Binomial estimate."""
    prob = simulate_wrapper(["a", "b"])
    expected = (2.0 / (2.0 + 1.0)) * (1.0 / (1.0 + 2.0))
    assert math.isclose(prob, expected)
