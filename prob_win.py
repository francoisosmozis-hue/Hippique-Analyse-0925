"""Training and prediction utilities for win/place probability models.

The module uses scikit-learn classifiers (LogisticRegression or
RandomForestClassifier) and calibrates the output probabilities with
isotonic regression via :class:`~sklearn.calibration.CalibratedClassifierCV`.
Models are persisted with :mod:`joblib` for later reuse.
"""

from pathlib import Path
from typing import Tuple
import pandas as pd
from joblib import dump, load
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.base import clone

from scripts.fetch_je_stats import fetch_je_stats
from scripts.fetch_je_chrono import fetch_je_chrono


def load_features(stats_source: str, chrono_source: str, on: str = "id") -> pd.DataFrame:
    """Combine J/E stats and chrono features into a single DataFrame."""
    stats = fetch_je_stats(stats_source)
    chrono = fetch_je_chrono(chrono_source)
    return stats.merge(chrono, on=on, how="outer")


def _base_estimator(model_type: str):
    if model_type == "random_forest":
        return RandomForestClassifier(n_estimators=200, random_state=0)
    return LogisticRegression(max_iter=1000)


def train_models(
    features: pd.DataFrame,
    model_type: str = "logistic",
    save_dir: str = "models",
) -> Tuple[CalibratedClassifierCV, CalibratedClassifierCV]:
    """Train models for win and place probabilities.

    The DataFrame ``features`` must contain the binary targets ``win`` and
    ``place``. Remaining columns are treated as predictors.
    """
    X = features.drop(columns=["win", "place"])
    y_win = features["win"]
    y_place = features["place"]

    estimator = _base_estimator(model_type)
    win_model = CalibratedClassifierCV(clone(estimator), cv=5, method="isotonic")
    win_model.fit(X, y_win)

    place_model = CalibratedClassifierCV(clone(estimator), cv=5, method="isotonic")
    place_model.fit(X, y_place)

    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dump(win_model, out_dir / "model_win.joblib")
    dump(place_model, out_dir / "model_place.joblib")

    return win_model, place_model


def load_models(save_dir: str = "models") -> Tuple[CalibratedClassifierCV, CalibratedClassifierCV]:
    """Load previously fitted win and place models."""
    path = Path(save_dir)
    win_model = load(path / "model_win.joblib")
    place_model = load(path / "model_place.joblib")
    return win_model, place_model


def predict(
    win_model: CalibratedClassifierCV,
    place_model: CalibratedClassifierCV,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Return calibrated win and place probabilities for each row of ``features``."""
    X = features.drop(columns=["win", "place"], errors="ignore")
    p_win = win_model.predict_proba(X)[:, 1]
    p_place = place_model.predict_proba(X)[:, 1]
    return pd.DataFrame({"p_win": p_win, "p_place": p_place})
