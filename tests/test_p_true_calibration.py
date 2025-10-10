import logging
import math

import pandas as pd
import pytest

import pipeline_run
from calibration import p_true_model
from calibration.p_true_model import (
    compute_runner_features,
    get_model_metadata,
    load_p_true_model,
    predict_probability,
)

def test_get_model_metadata_returns_copy() -> None:
    model = p_true_model.PTrueModel()
    model.metadata = {"n_samples": 12, "n_races": 3, "notes": {"foo": "bar"}}

    metadata = get_model_metadata(model)
    assert metadata == {"n_samples": 12, "n_races": 3}

    metadata["n_samples"] = 999
    assert model.metadata["n_samples"] == 12


def test_build_p_true_downgrades_to_heuristic_when_history_short(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = {
        "JE_BONUS_COEF": 0.0,
        "DRIFT_COEF": 0.0,
        "P_TRUE_MIN_SAMPLES": 100,
    }
    partants = [{"id": "1"}, {"id": "2"}]
    odds = {"1": 2.0, "2": 4.0}
    stats: dict[str, dict] = {}

    heur_expected = pipeline_run._heuristic_p_true(cfg, partants, odds, odds, stats)

    model = p_true_model.PTrueModel()
    model.metadata = {"n_samples": 12, "n_races": 3}

    monkeypatch.setattr(pipeline_run, "load_p_true_model", lambda: model)

    with caplog.at_level(logging.WARNING):
        result = pipeline_run.build_p_true(cfg, partants, odds, odds, stats)

    assert result == heur_expected
    assert "Calibration p_true ignorée" in caplog.text
