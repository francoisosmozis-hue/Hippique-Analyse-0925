import os
import sys

import pytest
 
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from validator_ev import ValidationError, validate_ev, validate_inputs

def test_validate_ev_passes_with_defaults(monkeypatch):
    monkeypatch.delenv("EV_MIN_SP", raising=False)
    monkeypatch.delenv("EV_MIN_GLOBAL", raising=False)
    assert validate_ev(ev_sp=0.5, ev_global=0.5)
 
def test_validate_ev_sp_below_threshold(monkeypatch):
    monkeypatch.setenv("EV_MIN_SP", "0.2")
    with pytest.raises(ValidationError):
        validate_ev(ev_sp=0.1, ev_global=1.0)

def test_validate_ev_combo_optional(monkeypatch):
    monkeypatch.setenv("EV_MIN_SP", "0.2")
    assert validate_ev(ev_sp=0.3, ev_global=None, need_combo=False)

def test_validate_ev_combo_required(monkeypatch):
    monkeypatch.setenv("EV_MIN_SP", "0.2")
    monkeypatch.setenv("EV_MIN_GLOBAL", "0.4")
    with pytest.raises(ValidationError):
        validate_ev(ev_sp=0.5, ev_global=0.2, need_combo=True)


def _sample_partants(n=6):
    return [{"id": str(i)} for i in range(1, n + 1)]


def _sample_odds(n=6):
    return {str(i): float(i + 1) for i in range(1, n + 1)}


def test_validate_inputs_ok():
    cfg = {}
    partants = _sample_partants()
    odds = _sample_odds()
    stats = {"coverage": 80}
    assert validate_inputs(cfg, partants, odds, stats)


def test_validate_inputs_partants_insuffisants():
    partants = _sample_partants(5)
    odds = _sample_odds(5)
    stats = {"coverage": 80}
    with pytest.raises(ValidationError):
        validate_inputs({}, partants, odds, stats)


def test_validate_inputs_cote_none():
    partants = _sample_partants()
    odds = _sample_odds()
    odds["3"] = None
    stats = {"coverage": 80}
    with pytest.raises(ValidationError):
        validate_inputs({}, partants, odds, stats)


def test_validate_inputs_couverture():
    partants = _sample_partants()
    odds = _sample_odds()
    stats = {"coverage": 70}
    with pytest.raises(ValidationError):
        validate_inputs({}, partants, odds, stats)

    cfg = {"ALLOW_JE_NA": True}
    assert validate_inputs(cfg, partants, odds, stats)
