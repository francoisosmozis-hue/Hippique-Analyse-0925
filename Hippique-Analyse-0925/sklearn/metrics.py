"""Lightweight replacements for selected scikit-learn metrics."""

from __future__ import annotations

import numpy as np


def brier_score_loss(y_true, y_prob):  # pragma: no cover - simple helper
    y_true_arr = np.asarray(y_true, dtype=float)
    y_prob_arr = np.asarray(y_prob, dtype=float)
    if y_true_arr.shape != y_prob_arr.shape:
        raise ValueError("y_true and y_prob must have the same shape")
    return float(np.mean((y_prob_arr - y_true_arr) ** 2))


def log_loss(y_true, y_prob, *, labels=None):  # pragma: no cover - simple helper
    y_true_arr = np.asarray(y_true, dtype=float)
    y_prob_arr = np.asarray(y_prob, dtype=float)
    if y_true_arr.shape != y_prob_arr.shape:
        raise ValueError("y_true and y_prob must have the same shape")
    y_prob_arr = np.clip(y_prob_arr, 1e-15, 1 - 1e-15)
    loss = -y_true_arr * np.log(y_prob_arr) - (1 - y_true_arr) * np.log(1 - y_prob_arr)
    return float(np.mean(loss))
