#!/usr/bin/env python3
"""Calibrate simulation probabilities using a Beta-Binomial model.

This script updates the win probability of each combination ("combiné")
based on past results.  The calibration file stores ``alpha`` and ``beta``
parameters of a Beta distribution along with the implied probability.

The results CSV is expected to contain at least two columns:
``combination`` (identifier of the combiné) and ``win`` (1 if the
combination succeeded, 0 otherwise).
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict

import yaml


def update_probabilities(results_file: str, calibration_file: str) -> Dict[str, float]:
    """Update calibrated probabilities using a Beta-Binomial model.

    Parameters
    ----------
    results_file:
        Path to a CSV file containing historical results.  It must provide the
        columns ``combination`` and ``win`` (1 or 0).
    calibration_file:
        Path to a YAML file where calibration parameters will be stored.

    Returns
    -------
    dict
        Mapping of combination identifiers to their updated probability.
    """
    # Load existing calibration parameters if available
    calib_path = Path(calibration_file)
    if calib_path.exists():
        with calib_path.open("r", encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or {}
    else:
        existing = {}

    params: Dict[str, Dict[str, float]] = defaultdict(lambda: {"alpha": 1.0, "beta": 1.0})
    for key, val in existing.items():
        alpha = float(val.get("alpha", 1.0))
        beta = float(val.get("beta", 1.0))
        params[key] = {"alpha": alpha, "beta": beta}

    # Incorporate new results
    with open(results_file, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if "combination" not in reader.fieldnames or "win" not in reader.fieldnames:
            raise ValueError("CSV must contain 'combination' and 'win' columns")
        for row in reader:
            combo = row["combination"]
            win = int(row["win"])
            p = params[combo]
            if win:
                p["alpha"] += 1.0
            else:
                p["beta"] += 1.0

    # Compute posterior probabilities and write back to YAML
    out_data: Dict[str, Dict[str, float]] = {}
    for combo, p in params.items():
        alpha, beta = p["alpha"], p["beta"]
        prob = alpha / (alpha + beta)
        out_data[combo] = {"alpha": alpha, "beta": beta, "p": prob}

    calib_path.parent.mkdir(parents=True, exist_ok=True)
    with calib_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(out_data, fh, sort_keys=True)

    return {k: v["p"] for k, v in out_data.items()}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate simulator probabilities")
    parser.add_argument(
        "--results",
        required=True,
        help="CSV file containing past results",
    )
    parser.add_argument(
        "--calibration",
        default="calibration/probabilities.yaml",
        help="YAML file to store calibration parameters",
    )
    return parser.parse_args()


def main() -> None:  # pragma: no cover - CLI entry point
    args = _parse_args()
    update_probabilities(args.results, args.calibration)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
