import os
import sys

import pytest
 
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from validator_ev import ValidationError, validate_ev

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
