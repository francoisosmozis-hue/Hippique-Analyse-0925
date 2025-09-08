import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import numpy as np
import pytest
from sklearn.metrics import log_loss

from prob_model import calibrated_sample


def test_probabilities_sum_to_one():
    labels, probs = calibrated_sample(n=100, seed=42)
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_calibrated_log_loss():
    labels, probs = calibrated_sample(n=1000, seed=0)
    loss = log_loss(labels, probs)
    assert loss == pytest.approx(0.8, rel=0.1)
