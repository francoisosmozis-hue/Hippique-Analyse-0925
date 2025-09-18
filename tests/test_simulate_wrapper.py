#!/usr/bin/env python3
import math
import os
import sys
from collections import OrderedDict

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
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)
    with pytest.raises(ValueError):
        sw.simulate_wrapper(["a"])


def test_combination_order(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Order of legs should not affect calibrated probability."""
    cal = tmp_path / "probabilities.yaml"
    cal.write_text("2|1:\n  alpha: 1\n  beta: 1\n  p: 0.25\n")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)
    p1 = sw.simulate_wrapper([1, 2])
    p2 = sw.simulate_wrapper([2, 1])
    assert math.isclose(p1, 0.25) and math.isclose(p2, 0.25)


def test_cache_prevents_recomputation(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Repeated calls to a missing combination should use cached result."""
    cal = tmp_path / "probabilities.yaml"
    cal.write_text("")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
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
    assert counter["iters"] == 1

    counter["iters"] = 0
    sw.simulate_wrapper(legs)
    assert counter["iters"] == 1


def test_cache_eviction(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Oldest entries are evicted when cache exceeds ``MAX_CACHE_SIZE``."""
    cal = tmp_path / "probabilities.yaml"
    cal.write_text("")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)
    monkeypatch.setattr(sw, "MAX_CACHE_SIZE", 2)

    sw.simulate_wrapper(["a"])  # cache: a
    sw.simulate_wrapper(["b"])  # cache: a, b
    assert list(sw._calibration_cache.keys()) == ["a", "b"]

    sw.simulate_wrapper(["c"])  # should evict "a"
    assert list(sw._calibration_cache.keys()) == ["b", "c"]


def test_fallback_uses_leg_probabilities(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Probabilities provided on legs override calibration and odds."""
    cal = tmp_path / "probabilities.yaml"
    cal.write_text("")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)

    legs = [{"id": "L1", "p": 0.2}, {"id": "L2", "p_true": 0.3}]
    prob = sw.simulate_wrapper(legs)
    assert math.isclose(prob, 0.2 * 0.3)
    key = sw._combo_key(legs)
    assert set(sw._calibration_cache[key]["sources"]) == {"leg_p", "leg_p_true"}


def test_fallback_uses_implied_odds(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """When no probabilities exist, implied odds provide a conservative floor."""
    cal = tmp_path / "probabilities.yaml"
    cal.write_text("")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)

    legs = [{"id": "L1", "odds": 5.0}, {"id": "L2", "odds": 4.0}]
    prob = sw.simulate_wrapper(legs)
    expected = (1 / 5.0) * (1 / 4.0)
    assert math.isclose(prob, expected)
    key = sw._combo_key(legs)
    assert sw._calibration_cache[key]["sources"] == ["implied_odds"]
