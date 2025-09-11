#!/usr/bin/env python3
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import simulate_wrapper as sw


def test_beta_binomial_fallback() -> None:
    """Missing combinations use a Beta-Binomial estimate."""
    prob = sw.simulate_wrapper(["a", "b"])
    expected = (2.0 / (2.0 + 1.0)) * (1.0 / (1.0 + 2.0))
    assert math.isclose(prob, expected)


def test_invalid_calibration(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Invalid calibration values should raise ``ValueError``."""
    bad = tmp_path / "probabilities.yaml"
    bad.write_text("a:\n  alpha: 1\n  beta: 1\n  p: 2\n")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", bad)
    monkeypatch.setattr(sw, "_calibration_cache", {})
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)
    with pytest.raises(ValueError):
        sw.simulate_wrapper(["a"])


def test_combination_order(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Order of legs should not affect calibrated probability."""
    cal = tmp_path / "probabilities.yaml"
    cal.write_text("2|1:\n  alpha: 1\n  beta: 1\n  p: 0.25\n")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", {})
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)
    p1 = sw.simulate_wrapper([1, 2])
    p2 = sw.simulate_wrapper([2, 1])
    assert math.isclose(p1, 0.25) and math.isclose(p2, 0.25)


def test_cache_prevents_recomputation(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Repeated calls to a missing combination should use cached result."""
    cal = tmp_path / "probabilities.yaml"
    cal.write_text("")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", {})
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)

    counter = {"iters": 0}

    class CountingIterable:
        def __init__(self, items):
            self.items = items

        def __iter__(self):
            counter["iters"] += 1
            return iter(self.items)

    legs = CountingIterable(["x", "y"])

    sw.simulate_wrapper(legs)
    assert counter["iters"] == 2

    counter["iters"] = 0
    sw.simulate_wrapper(legs)
    assert counter["iters"] == 1
