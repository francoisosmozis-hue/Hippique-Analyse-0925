"""Utilities to build and train a p_true calibration model from a flat CSV file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import datetime as dt
import math

import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
import yaml
import argparse


_EPSILON = 1e-9
_MIN_ODDS = 1.01


def assemble_dataset_from_csv(csv_path: Path) -> pd.DataFrame:
    """Return a dataframe from the flat CSV file."""
    
    df = pd.read_csv(csv_path)

    # Drop rows with missing odds
    df.dropna(subset=["cote"], inplace=True)
    df = df[df["cote"] >= _MIN_ODDS]

    # Create target variable
    df["is_winner"] = (df["arrivee_rang"] == 1).astype(float)

    # Create race identifier
    df["race_id"] = df["date"] + "_" + df["reunion"] + "_" + df["course"]

    # Feature engineering
    df["implied_prob"] = 1 / df["cote"]
    overround = df.groupby("race_id")["implied_prob"].transform("sum")
    df["p_market_no_vig"] = df["implied_prob"] / overround
    
    df["n_runners"] = df.groupby("race_id")["num"].transform("count")
    df["log_odds"] = df["cote"].apply(lambda x: math.log(max(x, _MIN_ODDS + _EPSILON)))
    
    # Placeholder for J/E stats and drift - to be populated with real data in future datasets
    df["j_rate"] = 0.0
    df["e_rate"] = 0.0
    df["je_total"] = 0.0
    df["drift"] = 0.0

    # Rename columns for compatibility
    df.rename(columns={"date": "race_date", "num": "runner_id", "cote": "odds_h5"}, inplace=True)

    return df


@dataclass(slots=True)
class CalibrationResult:
    """Container returned by :func:`train_and_evaluate_model`. """
    model: LogisticRegression
    features: list[str]
    n_train_samples: int
    n_test_samples: int
    train_brier_score: float
    train_log_loss: float
    test_brier_score: float
    test_log_loss: float
    fitted_at: dt.datetime


def train_and_evaluate_model(
    dataset: pd.DataFrame,
    *,
    split_date: str,
    features: Iterable[str] = ("log_odds", "n_runners", "p_market_no_vig"),
    C: float = 1.0,
    random_state: int = 42,
) -> CalibrationResult:
    """Fit a logistic regression on all available data."""

    df = dataset.copy()
    df = df.dropna(subset=["is_winner"])
    if df.empty:
        raise ValueError("dataset must contain at least one labelled sample")

    # Use all data for training
    train_df = df

    if train_df.empty:
        raise ValueError(f"no training data found")

    feature_list = [str(f) for f in features]
    X_train = train_df[feature_list].to_numpy()
    y_train = train_df["is_winner"].astype(int).to_numpy()

    model = LogisticRegression(
        C=float(C),
        solver="lbfgs",
        max_iter=1000,
        random_state=random_state,
    )
    model.fit(X_train, y_train)

    # Evaluate on training set itself
    proba_train = model.predict_proba(X_train)[:, 1]
    train_brier = float(brier_score_loss(y_train, proba_train))
    train_loss = float(log_loss(y_train, proba_train, labels=[0, 1]))

    return CalibrationResult(
        model=model,
        features=feature_list,
        n_train_samples=int(len(train_df)),
        n_test_samples=0, # No test set
        train_brier_score=train_brier,
        train_log_loss=train_loss,
        test_brier_score=0.0,
        test_log_loss=0.0,
        fitted_at=dt.datetime.now(dt.timezone.utc),
    )


def serialize_model(result: CalibrationResult, path: Path, *, C: float = 1.0, version: int = 4) -> None:
    """Write ``result`` to ``path`` using the repository YAML schema."""

    coefs = result.model.coef_[0]
    intercept = float(result.model.intercept_[0])

    payload = {
        "version": version,
        "features": result.features,
        "intercept": intercept,
        "coefficients": {
            name: float(value)
            for name, value in zip(result.features, coefs, strict=True)
        },
        "metadata": {
            "regularization": float(C),
            "n_train_samples": result.n_train_samples,
            "n_test_samples": result.n_test_samples,
            "train_brier_score": result.train_brier_score,
            "train_log_loss": result.train_log_loss,
            "test_brier_score": result.test_brier_score,
            "test_log_loss": result.test_log_loss,
            "fitted_at": result.fitted_at.isoformat().replace("+00:00", "Z"),
        },
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train and evaluate the p_true model from a CSV file.")
    parser.add_argument(
        "--csv-file",
        type=Path,
        default=Path("fr_2025_sept_partants_cotes_arrivees.csv"),
        help="Path to the input CSV file."
    )
    parser.add_argument(
        "--output-model",
        type=Path,
        default=Path("calibration/p_true_model_v5.yaml"),
        help="Path to save the trained model YAML file."
    )
    args = parser.parse_args()

    if not args.csv_file.exists():
        print(f"ERREUR : Le fichier CSV '{args.csv_file}' n'a pas été trouvé.")
        exit(1)

    print(f"1. Assembling dataset from {args.csv_file}...")
    dataset = assemble_dataset_from_csv(args.csv_file)
    print(f"   Found {len(dataset)} total records.")

    split_date = "2025-09-15"
    
    # Define the new feature set for the v5 model
    features_v5 = ["log_odds", "n_runners", "p_market_no_vig", "j_rate", "e_rate", "je_total", "drift"]
    
    print(f"\n2. Training and evaluating model v5 with split date {split_date}...")
    print(f"   Features: {features_v5}")
    
    try:
        result = train_and_evaluate_model(dataset, split_date=split_date, features=features_v5)
        
        print(f"\n--- Evaluation on Test Set (>= {split_date}) ---")
        print(f"   Test samples: {result.n_test_samples}")
        print(f"   Brier Score: {result.test_brier_score:.4f}")
        print(f"   Log Loss: {result.test_log_loss:.4f}")
        
        print(f"\n3. Serializing model to {args.output_model}...")
        serialize_model(result, args.output_model, version=5)
        
        print("\nDone.")
    except ValueError as e:
        print(f"\nERREUR : {e}")
        print("   Il est possible que le jeu de données ne contienne pas de données des deux côtés de la date de césure.")