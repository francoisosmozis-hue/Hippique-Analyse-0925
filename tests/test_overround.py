from __future__ import annotations

import pytest

from hippique_orchestrator.overround import adaptive_cap, compute_overround_place


def test_compute_overround_place_nominal():
    """Test with standard 'cote_place' odds."""
    runners = [
        {"cote_place": 2.0},  # 0.5
        {"cote_place": 4.0},  # 0.25
        {"cote_place": 4.0},  # 0.25
    ]
    assert compute_overround_place(runners) == pytest.approx(1.0)


def test_compute_overround_place_with_odds_place_fallback():
    """Test fallback to 'odds_place'."""
    runners = [
        {"odds_place": 2.5},  # 0.4
        {"odds_place": 5.0},  # 0.2
    ]
    assert compute_overround_place(runners) == pytest.approx(0.6)


def test_compute_overround_place_with_cote_fallback():
    """Test fallback to 'cote' when place odds are missing."""
    runners = [
        {"cote": 3.0},  # 0.333...
        {"cote_place": None, "cote": 6.0},  # 0.166...
    ]
    assert compute_overround_place(runners) == pytest.approx(0.5)


def test_compute_overround_place_mixed_sources():
    """Test with a mix of all possible odds keys."""
    runners = [
        {"cote_place": 2.0},  # 0.5
        {"odds_place": 4.0},  # 0.25
        {"cote": 10.0},  # 0.1
        {"useless_key": 1.0},  # Skipped
    ]
    assert compute_overround_place(runners) == pytest.approx(0.85)


def test_compute_overround_place_handles_invalid_data():
    """Test that invalid entries are skipped gracefully."""
    runners = [
        {"cote_place": 2.0},  # 0.5
        "not-a-dict",
        {"cote_place": "invalid"},
        {"cote_place": 0.0},  # Invalid odds
        {"cote_place": -5.0},  # Invalid odds
        None,
        {},
    ]
    assert compute_overround_place(runners) == pytest.approx(0.5)


def test_compute_overround_place_empty_list():
    """Test with an empty list of runners."""
    assert compute_overround_place([]) == 0.0


def test_compute_overround_place_no_valid_odds(caplog):
    """Test when no runners have valid odds."""
    runners = [
        {"name": "Runner 1"},
        {"name": "Runner 2"},
    ]
    assert compute_overround_place(runners) == 0.0
    assert "Could not calculate place overround" in caplog.text


def test_adaptive_cap_returns_base_cap():
    """Test that the placeholder adaptive_cap returns the base cap."""
    assert adaptive_cap(p_place=0.5, volatility=0.2) == 0.6
    assert adaptive_cap(p_place=None, volatility=None, base_cap=0.8) == 0.8
