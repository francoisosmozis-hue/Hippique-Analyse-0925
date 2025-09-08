import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pytest

import ev_calculator as ec


def test_compute_ev_roi_profit():
    ev, roi = ec.compute_ev_roi(p=0.6, odds=2.0, stake=5)
    assert ev == pytest.approx(1.0)
    assert roi == pytest.approx(0.2)


def test_compute_ev_roi_loss():
    ev, roi = ec.compute_ev_roi(p=0.25, odds=3.0, stake=2)
    assert ev == pytest.approx(-0.5)
    assert roi == pytest.approx(-0.25)
