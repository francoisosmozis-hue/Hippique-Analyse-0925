#!/usr/bin/env python3
"""Tests for calibration decay weighting."""

import csv
from pathlib import Path

import pytest

from calibration import calibrate_simulator as calibrate


@pytest.mark.parametrize("recent_wins", [5, 8])
def test_recent_wins_gain_weight(tmp_path: Path, recent_wins: int) -> None:
    """Recent victories should have more impact with exponential decay."""

    results_path = tmp_path / "results.csv"
    with results_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["combination", "win"])
        writer.writeheader()
        for _ in range(50):
            writer.writerow({"combination": "combo", "win": 0})
        for _ in range(recent_wins):
            writer.writerow({"combination": "combo", "win": 1})

    calib_decay = tmp_path / "decay.yaml"
    calib_reference = tmp_path / "reference.yaml"

    probs_decay = calibrate.update_probabilities(
        str(results_path),
        str(calib_decay),
        decay=calibrate.DEFAULT_DECAY,
    )
    probs_reference = calibrate.update_probabilities(
        str(results_path),
        str(calib_reference),
        decay=1.0,
    )

    assert probs_decay["combo"] > probs_reference["combo"]
