import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from hippique_orchestrator.scripts import simulate_wrapper as sw
from hippique_orchestrator.scripts.simulate_wrapper import (
    _load_calibration,
    _load_correlation_settings,
    evaluate_combo,
    simulate_wrapper,
)


@pytest.fixture
def clear_caches():
    """Clear module-level caches before each test."""

    sw._calibration_cache.clear()
    sw._calibration_mtime = 0.0
    sw._correlation_settings.clear()
    sw._correlation_mtime = 0.0
    # Also reset the path to default to avoid test pollution
    sw.PAYOUT_CALIBRATION_PATH = sw._default_payout_calibration_path()
    yield


@pytest.fixture
def fake_fs_for_wrapper(fs):
    """Setup pyfakefs with a calibration file."""
    # Using a path pyfakefs understands
    calib_path = Path("/etc/config/probabilities.yaml")
    fs.create_file(calib_path)
    
    initial_data = {
        "A|B": {"alpha": 8, "beta": 2, "p": 0.8},
    }
    calib_path.write_text(yaml.dump(initial_data))
    
    # Patch the global path variable to use our fake path
    with patch("hippique_orchestrator.scripts.simulate_wrapper.CALIBRATION_PATH", calib_path):
        yield fs


def test_load_calibration_reloads_on_file_change(fake_fs_for_wrapper, clear_caches):
    """
    Ensures that the calibration file is reloaded when its modification time changes.
    """
    calib_path = Path("/etc/config/probabilities.yaml")

    # 1. First call, loads initial data
    prob1 = simulate_wrapper(["A", "B"])
    assert prob1 == pytest.approx(0.8)

    # 2. Modify the file
    time.sleep(0.01) # Ensure mtime is different
    new_data = {
         "A|B": {"alpha": 2, "beta": 8, "p": 0.2},
    }
    calib_path.write_text(yaml.dump(new_data))
    
    # 3. Second call should trigger a reload
    prob2 = simulate_wrapper(["A", "B"])
    assert prob2 == pytest.approx(0.2)


def test_empty_or_invalid_calibration_file(fs, clear_caches):
    """
    Tests that the wrapper handles empty or invalid YAML files gracefully.
    """
    calib_path = Path("/etc/config/probabilities.yaml")
    fs.create_file(calib_path)
    
    with patch("hippique_orchestrator.scripts.simulate_wrapper.CALIBRATION_PATH", calib_path):
        # Test with an empty file - should not raise error, should fallback
        calib_path.write_text("")
        assert simulate_wrapper(['C', 'D']) == pytest.approx(0.25)

        # Test with an invalid YAML file - should not raise error, should fallback
        calib_path.write_text("key: value: invalid:")
        # We need to clear cache to force a reload
        _load_calibration()
        assert simulate_wrapper(['C', 'D']) == pytest.approx(0.25)


def test_simulate_wrapper_fallback_no_correlation(clear_caches):
    """
    Test that the wrapper falls back to multiplying independent probabilities
    when no calibration or correlation is found.
    """
    legs = [{"id": "X", "odds": 2.0}, {"id": "Y", "odds": 4.0}] # p=0.5, p=0.25
    prob = simulate_wrapper(legs)
    assert prob == pytest.approx(0.5 * 0.25)


def test_correlation_penalty_defaults_gracefully(fs, clear_caches):
    """
    Test that correlation penalty is applied even when settings file is empty.
    """
    payout_calib_path = Path("/etc/config/payout_calibration.yaml")
    fs.create_file(payout_calib_path, contents=yaml.dump({}))
    
    legs = [
        {"id": 1, "odds": 2.0, "rc": "R1C1"},
        {"id": 2, "odds": 2.0, "rc": "R1C1"},
    ]
    
    with patch("hippique_orchestrator.scripts.simulate_wrapper.PAYOUT_CALIBRATION_PATH", payout_calib_path):
        prob = simulate_wrapper(legs)
        # Should apply the default penalty (0.85)
        assert prob == pytest.approx((0.5 * 0.5) * 0.85)


def test_simulate_wrapper_applies_correlation_penalty(fs, clear_caches):
    """
    Test that a specific correlation penalty from the calibration file is applied.
    """
    payout_calib_path = Path("/etc/config/payout_calibration.yaml")
    fs.create_file(payout_calib_path)
    
    payout_calib_data = {"correlations": {"rc": {"penalty": 0.7}}}
    payout_calib_path.write_text(yaml.dump(payout_calib_data))

    legs = [
        {"id": 1, "odds": 2.0, "rc": "R1C1"}, # p=0.5
        {"id": 2, "odds": 4.0, "rc": "R1C1"}, # p=0.25
    ]
    
    with patch("hippique_orchestrator.scripts.simulate_wrapper.PAYOUT_CALIBRATION_PATH", payout_calib_path):
        _load_correlation_settings() # Force reload
        prob = simulate_wrapper(legs)
        # Expected = (0.5 * 0.25) * 0.7
        assert prob == pytest.approx(0.0875)

def test_monte_carlo_is_used_when_numpy_present(fs, clear_caches):
    """
    Test that Monte Carlo simulation is used when numpy is available and rho is set.
    """
    # Guard the test: only run if numpy is installed
    np = pytest.importorskip("numpy")

    payout_calib_path = Path("/etc/config/payout_calibration.yaml")
    fs.create_file(payout_calib_path)
    
    payout_calib_data = {"correlations": {"rc": {"rho": 0.5, "samples": 10000}}}
    payout_calib_path.write_text(yaml.dump(payout_calib_data))

    legs = [
        {"id": 1, "odds": 2.0, "rc": "R1C1"}, # p=0.5
        {"id": 2, "odds": 4.0, "rc": "R1C1"}, # p=0.25
    ]
    
    with patch("hippique_orchestrator.scripts.simulate_wrapper.PAYOUT_CALIBRATION_PATH", payout_calib_path):
        _load_correlation_settings()
        prob = simulate_wrapper(legs)
        
        # Base probability is 0.125. With positive correlation, joint probability should be higher.
        # The exact MC result is hard to pin down, so we check it's higher than the independent prob.
        # And not equal to the default penalty.
        assert prob > 0.125
        assert prob != pytest.approx((0.5 * 0.25) * 0.85)

def test_monte_carlo_is_skipped_when_numpy_missing(fs, clear_caches):
    """
    Test that the simulation falls back to penalty when numpy is not available.
    """
    payout_calib_path = Path("/etc/config/payout_calibration.yaml")
    fs.create_file(payout_calib_path)
    
    payout_calib_data = {"correlations": {"rc": {"rho": 0.5}}}
    payout_calib_path.write_text(yaml.dump(payout_calib_data))

    legs = [
        {"id": 1, "odds": 2.0, "rc": "R1C1"},
        {"id": 2, "odds": 2.0, "rc": "R1C1"},
    ]
    
    with patch("hippique_orchestrator.scripts.simulate_wrapper.PAYOUT_CALIBRATION_PATH", payout_calib_path):
        with patch("hippique_orchestrator.scripts.simulate_wrapper.np", None): # Mock numpy as missing
            _load_correlation_settings()
            prob = simulate_wrapper(legs)
            # Should fallback to the default penalty as rho cannot be used without numpy
            assert prob == pytest.approx((0.5 * 0.5) * 0.85)

def test_evaluate_combo_calls_dependencies_and_returns_results(fs, clear_caches):
    """
    Test that evaluate_combo uses simulate_wrapper and compute_ev_roi correctly.
    """
    payout_calib_path = Path("/etc/config/payout_calibration.yaml")
    fs.create_file(payout_calib_path, contents=yaml.dump({}))

    tickets = [
        {"legs": ["A", "B"], "payout": 10.0, "stake": 1},
        {"legs": ["C"], "payout": 5.0, "stake": 1},
    ]
    
    mock_stats = {
        "ev_ratio": 0.15,
        "roi": 0.20,
        "combined_expected_payout": 1.2,
        "sharpe": 0.5,
        "ticket_metrics": [],
    }

    with patch("hippique_orchestrator.scripts.simulate_wrapper.compute_ev_roi", return_value=mock_stats) as mock_compute_ev:
        with patch("hippique_orchestrator.scripts.simulate_wrapper.simulate_wrapper", return_value=0.1) as mock_simulate:
            result = evaluate_combo(tickets, bankroll=100, calibration=payout_calib_path)

            # Check that the main orchestrator was called
            mock_compute_ev.assert_called_once()
            
            # Check that simulate_wrapper was used as the simulate_fn
            assert mock_compute_ev.call_args[1]["simulate_fn"] == mock_simulate
            
            # Check that results from compute_ev_roi are passed through
            assert result["status"] == "ok"
            assert result["ev_ratio"] == 0.15
            assert result["payout_expected"] == 1.2
            assert result["sharpe"] == 0.5
