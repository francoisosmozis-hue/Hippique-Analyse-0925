import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from validator_ev import ValidationError, validate_ev, validate_policy


def test_ev_sp_below_default_threshold(monkeypatch):
    monkeypatch.delenv("EV_MIN_SP", raising=False)
    with pytest.raises(ValidationError):
        validate_ev(ev_sp=0.14, ev_global=0.5)


def test_ev_global_below_default_threshold(monkeypatch):
    monkeypatch.delenv("EV_MIN_SP", raising=False)
    monkeypatch.delenv("EV_MIN_GLOBAL", raising=False)
    with pytest.raises(ValidationError):
        validate_ev(ev_sp=0.5, ev_global=0.34, need_combo=True)


def test_validate_policy_roi_below_threshold():
    with pytest.raises(ValidationError):
        validate_policy(ev_global=1.0, roi_global=0.24, min_ev=0.0, min_roi=0.25)


def test_validate_policy_raises_on_low_roi_message():
    with pytest.raises(ValidationError, match="ROI global below threshold"):
        validate_policy(ev_global=1.0, roi_global=0.1, min_ev=0.0, min_roi=0.2)
