import os
import pathlib
import sys

import pytest
 
sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))
from validator_ev import must_have, validate_inputs


def sample_data():
    partants = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
    odds_h30 = {"1": 2.5, "2": 3.5}
    odds_h5 = {"1": 2.0, "2": 4.0}
    stats_je = {"1": {"j_win": 10, "e_win": 11}, "2": {"j_win": 9, "e_win": 8}}
    return partants, odds_h30, odds_h5, stats_je


def cfg(**overrides):
    base = {
        "ALLOW_JE_NA": False,
        "REQUIRE_DRIFT_LOG": True,
        "REQUIRE_ODDS_WINDOWS": [30, 5],
     }
    base.update(overrides)
    return base


def test_must_have_raises():
    with pytest.raises(RuntimeError):
        must_have([], "manquant")


def test_validate_inputs_ok():
    partants, odds_h30, odds_h5, stats_je = sample_data()
    assert validate_inputs(cfg(), partants, odds_h30, odds_h5, stats_je)


def test_incoherent_partants():
    partants, odds_h30, odds_h5, stats_je = sample_data()
    odds_h5["3"] = 5.0
    with pytest.raises(ValueError):
        validate_inputs(cfg(), partants, odds_h30, odds_h5, stats_je)
    

def test_missing_stats_blocked():
    partants, odds_h30, odds_h5, stats_je = sample_data()
    stats_je.pop("1")
    with pytest.raises(ValueError):
        validate_inputs(cfg(), partants, odds_h30, odds_h5, stats_je)


def test_missing_required_window():
    partants, _h30, odds_h5, stats_je = sample_data()
    with pytest.raises(RuntimeError):
        validate_inputs(cfg(), partants, None, odds_h5, stats_je)


def test_require_drift_log():
    partants, odds_h30, _h5, stats_je = sample_data()
    with pytest.raises(RuntimeError):
        validate_inputs(cfg(REQUIRE_ODDS_WINDOWS=[]), partants, odds_h30, None, stats_je)


def test_invalid_odds_value():
    partants, odds_h30, odds_h5, stats_je = sample_data()
    odds_h30["1"] = "abc"
    with pytest.raises(ValueError):
        validate_inputs(cfg(), partants, odds_h30, odds_h5, stats_je)
