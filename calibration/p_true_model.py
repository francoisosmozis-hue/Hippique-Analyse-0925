"""Loader and inference helpers for the :math:`p_true` calibration model."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

MODEL_PATH = Path("calibration/p_true_model.yaml")
_EPSILON = 1e-9

_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: tuple[Path, float, "PTrueModel"] | None = None


@dataclass(frozen=True, slots=True)
class PTrueModel:
    """Representation of a serialized prediction model."""

    model: Any  # The actual model object, e.g., LGBMClassifier
    features: tuple[str, ...]
    metadata: dict

    def predict(self, features: Mapping[str, float]) -> float:
        """Predict probability for a single observation."""
        try:
            # Create the feature vector in the correct order
            feature_vector = [[features.get(name, 0.0) for name in self.features]]
            # Predict probability for the positive class (winner)
            proba = self.model.predict_proba(feature_vector)[:, 1]
            return proba[0]
        except Exception as e:
            # Log error if prediction fails for some reason
            # logger.error(f"Model prediction failed: {e}")
            return _EPSILON

    def get_metadata(self) -> dict[str, Any]:
        """Return a shallow copy of the calibration metadata."""
        return get_model_metadata(self)


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _ensure_probability(prob: float) -> float:
    if prob <= 0.0:
        return _EPSILON
    if prob >= 1.0:
        return 1.0 - _EPSILON
    return prob


def load_p_true_model(path: Path | None = None) -> PTrueModel | None:
    """Return cached :class:`PTrueModel` when available on disk."""

    path = Path(path or MODEL_PATH)

    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None

    global _MODEL_CACHE
    with _MODEL_LOCK:
        if _MODEL_CACHE and _MODEL_CACHE[0] == path and _MODEL_CACHE[1] == mtime:
            return _MODEL_CACHE[2]

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        
        # Handle new LightGBM format
        if data.get("model_format") == "lightgbm_joblib":
            import joblib
            model_path = path.parent / data["model_path"]
            if not model_path.exists():
                raise FileNotFoundError(f"Model file not found: {model_path}")
            
            model_obj = joblib.load(model_path)
            features = tuple(str(f) for f in data.get("features", ()))
            metadata = dict(data.get("metadata", {}))
            
            model = PTrueModel(
                model=model_obj,
                features=features,
                metadata=metadata,
            )
            _MODEL_CACHE = (path, mtime, model)
            return model
        
        # Fallback for old Logistic Regression format (if needed, otherwise remove)
        features = tuple(str(f) for f in data.get("features", ()))
        if not features or "coefficients" not in data:
            return None # Not a recognizable format

        # This part is now legacy and will be removed in future versions.
        # It reconstructs a model object that behaves like a scikit-learn model.
        @dataclass
        class _LegacyModel:
            intercept: float
            coefficients: dict[str, float]
            features: tuple[str, ...]

            def predict_proba(self, X) -> list[list[float]]:
                score = self.intercept + sum(self.coefficients.get(name, 0.0) * val for name, val in zip(self.features, X[0]))
                prob = _sigmoid(score)
                return [[1 - prob, prob]]

        intercept = float(data.get("intercept", 0.0))
        coeffs_raw = data.get("coefficients", {})
        coefficients = {str(k): float(v) for k, v in coeffs_raw.items()}
        metadata = dict(data.get("metadata", {}))

        legacy_model_obj = _LegacyModel(intercept=intercept, coefficients=coefficients, features=features)

        model = PTrueModel(
            model=legacy_model_obj,
            features=features,
            metadata=metadata,
        )
        _MODEL_CACHE = (path, mtime, model)
        return model


def get_model_metadata(model: PTrueModel | None) -> dict[str, Any]:
    """Return sanitized calibration metadata for ``model``.

    Only scalar values (``str``/``int``/``float``/``bool``) are exposed in the
    returned mapping to avoid leaking nested structures. When ``model`` is
    ``None`` or metadata is missing, an empty dictionary is returned.
    """

    if model is None:
        return {}

    meta: Mapping[str, Any] | None = None
    if isinstance(model.metadata, Mapping):
        meta = model.metadata

    if meta is None:
        return {}

    sanitized: dict[str, Any] = {}
    for key, value in meta.items():
        if isinstance(value, (str, int, float, bool)):
            sanitized[str(key)] = value
    return dict(sanitized)


def compute_runner_features(
    odds_h5: float,
    odds_h30: float | None,
    stats: Mapping[str, float] | None,
) -> dict[str, float]:
    """Return the feature mapping expected by the calibration model."""

    o5 = max(float(odds_h5 or 0.0), 0.0)
    if not math.isfinite(o5) or o5 <= 1.0:
        raise ValueError("odds_h5 must be > 1 and finite")

    o30 = float(odds_h30) if odds_h30 not in (None, "") else o5
    if not math.isfinite(o30) or o30 <= 1.0:
        o30 = o5

    stats = stats or {}
    j_win = float(stats.get("j_win", 0.0))
    e_win = float(stats.get("e_win", 0.0))
    je_total = j_win + e_win

    return {
        "log_odds": math.log(max(o5, 1.0 + _EPSILON)),
        "drift": o5 - o30,
        "je_total": je_total,
        "implied_prob": 1.0 / o5,
    }


def predict_probability(
    model: PTrueModel,
    features: Mapping[str, float],
) -> float:
    """Return calibrated probability clipped to ``(0, 1)``."""

    prob = model.predict(features)
    return _ensure_probability(prob)
