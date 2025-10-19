"""Minimal linear models used in the test suite."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class LogisticRegression:  # pragma: no cover - simple numerical implementation
    """Very small subset of :class:`sklearn.linear_model.LogisticRegression`.

    The implementation is intentionally lightweight: it relies on batch
    gradient descent with an L2 penalty matching the ``C`` regularisation
    parameter.  Only the attributes exercised by the tests are provided.
    """

    C: float = 1.0
    solver: str = "lbfgs"
    max_iter: int = 1000
    random_state: int | None = None

    def __post_init__(self) -> None:
        self.coef_: np.ndarray | None = None
        self.intercept_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> LogisticRegression:
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)

        if X.ndim != 2:
            raise ValueError("X must be a 2D array")
        if y.shape[0] != X.shape[0]:
            raise ValueError("X and y must contain the same number of samples")

        n_samples, n_features = X.shape
        rng = np.random.default_rng(self.random_state)
        weights = rng.normal(scale=0.01, size=n_features)
        bias = 0.0

        learning_rate = 0.1
        regularisation = 0.0 if self.C == 0 else 1.0 / float(self.C)

        for _ in range(int(self.max_iter)):
            linear = X @ weights + bias
            preds = 1.0 / (1.0 + np.exp(-linear))
            error = preds - y

            grad_w = (X.T @ error) / n_samples + regularisation * weights
            grad_b = float(error.mean())

            update_norm = math.sqrt(float(np.dot(grad_w, grad_w) + grad_b * grad_b))
            weights -= learning_rate * grad_w
            bias -= learning_rate * grad_b

            if update_norm < 1e-6:
                break

        self.coef_ = weights.reshape(1, -1)
        self.intercept_ = np.array([bias], dtype=float)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.coef_ is None or self.intercept_ is None:
            raise ValueError("Model must be fitted before calling predict_proba")

        X = np.asarray(X, dtype=float)
        linear = X @ self.coef_[0] + self.intercept_[0]
        probs = 1.0 / (1.0 + np.exp(-linear))
        probs = np.clip(probs, 1e-9, 1 - 1e-9)
        return np.column_stack((1.0 - probs, probs))
