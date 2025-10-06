"""Lightweight fallback implementations mimicking selected scikit-learn APIs."""

from . import linear_model, metrics  # noqa: F401

__all__ = ["linear_model", "metrics"]
