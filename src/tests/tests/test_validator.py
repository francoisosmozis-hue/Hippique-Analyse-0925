import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from validator_ev import ValidationError, validate_inputs


def _sample_partants(n: int = 6):
    return [{"id": str(i)} for i in range(1, n + 1)]


def _sample_odds(n: int = 6):
    return {str(i): float(i + 1) for i in range(1, n + 1)}


def test_no_partants_raises():
    odds = _sample_odds()
    stats = {"coverage": 80}
    with pytest.raises(ValidationError):
        validate_inputs({}, [], odds, stats)


def test_no_odds_raises():
    partants = _sample_partants()
    stats = {"coverage": 80}
    with pytest.raises(ValidationError):
        validate_inputs({}, partants, {}, stats)


def test_no_stats_raises():
    partants = _sample_partants()
    odds = _sample_odds()
    with pytest.raises(ValidationError):
        validate_inputs({}, partants, odds, None)
