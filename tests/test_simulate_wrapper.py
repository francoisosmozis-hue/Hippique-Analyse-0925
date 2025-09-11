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
