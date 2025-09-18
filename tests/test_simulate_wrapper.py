#!/usr/bin/env python3
import math
import os
import sys
from collections import OrderedDict
from typing import Any, Dict

import pytest
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import simulate_wrapper as sw


def test_calibration_details_expose_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Cached calibrations should expose decay metadata within details."""

    cal = tmp_path / "probabilities.yaml"
    cal.write_text(
        """
__meta__:
  decay: 0.98
  half_life: 34.65735902799726
  generated_at: "2024-01-01T00:00:00+00:00"
a|b:
  alpha: 10
  beta: 5
  p: 0.6666666666666666
  weight: 15
  updated_at: "2024-02-01T12:00:00+00:00"
        """.strip()
    )

    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)
    monkeypatch.setattr(sw, "_calibration_metadata", {})

    prob = sw.simulate_wrapper(["a", "b"])
    assert prob == pytest.approx(10 / 15)

    cache_entry = sw._calibration_cache["a|b"]
    details = cache_entry.get("details") or {}
    cal_detail = details.get("__calibration__") or {}
    assert cal_detail.get("weight") == pytest.approx(15)
    assert cal_detail.get("updated_at") == "2024-02-01T12:00:00+00:00"
    assert cal_detail.get("decay") == pytest.approx(0.98)
    assert cal_detail.get("half_life") == pytest.approx(34.65735902799726)


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


def test_correlation_penalty_reduces_probability_and_ev(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Legs from the same meeting should trigger correlation penalties."""

    cal = tmp_path / "probabilities.yaml"
    cal.write_text("")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)
    monkeypatch.setattr(sw, "_calibration_metadata", {})

    payout = tmp_path / "payout_calibration.yaml"
    monkeypatch.setattr(sw, "PAYOUT_CALIBRATION_PATH", payout)
    monkeypatch.setattr(sw, "_correlation_settings", {})
    monkeypatch.setattr(sw, "_correlation_mtime", 0.0)

    legs = [
        {"id": "L1", "p": 0.6, "meeting": "R1", "race": "C1", "rc": "R1C1"},
        {"id": "L2", "p": 0.55, "meeting": "R1", "race": "C1", "rc": "R1C1"},
    ]

    def run_scenario(penalty: float, rho: float | None = None) -> tuple[float, float, list[dict]]:
        payload: Dict[str, Any] = {"correlations": {"meeting_course": {"penalty": penalty}}}
        if rho is not None:
            payload["correlations"]["meeting_course"]["rho"] = rho
            payload["correlations"]["meeting_course"]["samples"] = 4000
        payout.write_text(yaml.safe_dump(payload), encoding="utf-8")
        monkeypatch.setattr(sw, "_correlation_mtime", 0.0)
        monkeypatch.setattr(sw, "_correlation_settings", {})
        monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
        sw.set_correlation_penalty(penalty)
        prob = sw.simulate_wrapper(legs)
        entry = sw._calibration_cache[sw._combo_key(legs)]
        detail = entry.get("details") or {}
        corr_info = detail.get("__correlation__", [])
        from ev_calculator import compute_ev_roi

        ticket = {
            "odds": 4.0,
            "stake": 1.0,
            "legs": [leg["id"] for leg in legs],
            "legs_details": [dict(item) for item in legs],
        }
        stats = compute_ev_roi(
            [ticket],
            budget=10.0,
            simulate_fn=sw.simulate_wrapper,
            cache_simulations=False,
            round_to=0.0,
        )
        return prob, float(stats.get("ev", 0.0)), corr_info

    prob_neutral, ev_neutral, corr_neutral = run_scenario(1.0)
    assert corr_neutral, "Correlation metadata should be recorded even without penalty"

    prob_penalized, ev_penalized, corr_penalized = run_scenario(0.6, rho=-0.45)
    assert corr_penalized and corr_penalized[0]["method"] in {"penalty", "monte_carlo"}
    assert prob_penalized < prob_neutral
    assert ev_penalized < ev_neutral
