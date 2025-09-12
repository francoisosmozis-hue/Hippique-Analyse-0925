import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from validator_ev import ValidationError, validate_ev


def test_ev_sp_below_default_threshold(monkeypatch):
    monkeypatch.delenv("EV_MIN_SP", raising=False)
    with pytest.raises(ValidationError):
        validate_ev(ev_sp=0.19, ev_global=0.5)


def test_ev_global_below_default_threshold(monkeypatch):
    monkeypatch.delenv("EV_MIN_SP", raising=False)
    monkeypatch.delenv("EV_MIN_GLOBAL", raising=False)
    with pytest.raises(ValidationError):
        validate_ev(ev_sp=0.5, ev_global=0.39, need_combo=True)
