from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence
import threading

import yaml

MODEL_PATH = Path("calibration/p_true_model_v5.yaml")
_EPSILON = 1e-9
_MODEL_CACHE: tuple[Path, float, 'PTrueModel'] | None = None
_MODEL_LOCK = threading.Lock()


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


@dataclass(frozen=True)
class PTrueModel:
    """Calibrated logistic regression for p(true)."""

    features: Sequence[str]
    intercept: float
    coefficients: Mapping[str, float]
    metadata: dict

    def predict(self, features: Mapping[str, float]) -> float:
        score = float(self.intercept)
        for name in self.features:
            coef = float(self.coefficients.get(name, 0.0))
            value = float(features.get(name, 0.0))
            score += coef * value
        return _sigmoid(score)

    def get_metadata(self) -> dict[str, Any]:
        """Return a shallow copy of the calibration metadata."""
        return get_model_metadata(self)


def _yaml_load(path: str | Path) -> dict:
    """Load YAML content from ``path`` using ``yaml.safe_load``."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


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
        features = tuple(str(f) for f in data.get("features", ()))
        intercept = float(data.get("intercept", 0.0))
        coeffs_raw = data.get("coefficients", {})
        coefficients = {str(k): float(v) for k, v in coeffs_raw.items()}
        metadata = dict(data.get("metadata", {}))

        if not features:
            raise ValueError("calibration model does not define any feature")

        for name in features:
            coefficients.setdefault(name, 0.0)

        model = PTrueModel(
            features=features,
            intercept=intercept,
            coefficients=coefficients,
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




def predict_probability(
    model: PTrueModel,
    features: Mapping[str, float],
) -> float:
    """Return calibrated probability clipped to ``(0, 1)``."""
    prob = model.predict(features)
    return _ensure_probability(prob)