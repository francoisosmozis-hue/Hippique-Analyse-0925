from pathlib import Path

import pytest

import pipeline_run
from tests.test_pipeline_exotics_filters import (
    DEFAULT_CALIBRATION,
    _prepare_stubs,
    _write_inputs,
)


def test_pipeline_abstains_when_calibration_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_stats = {
        "status": "ok",
        "ev_ratio": 0.55,
        "payout_expected": 22.0,
        "roi": 0.25,
        "sharpe": 0.35,
    }

    _prepare_stubs(monkeypatch, eval_stats)
    inputs = _write_inputs(tmp_path)

    outdir = tmp_path / "out"
    result = pipeline_run.run_pipeline(
        h30=str(inputs["h30"]),
        h5=str(inputs["h5"]),
        stats_je=str(inputs["stats"]),
        partants=str(inputs["partants"]),
        gpi=str(inputs["gpi"]),
        outdir=str(outdir),
        calibration=str(tmp_path / "missing_calibration.yaml"),
    )

    metrics = result["metrics"]
    assert metrics["status"] == "insufficient_data"
    assert metrics["tickets"]["total"] == 0
    assert "calibration_missing" in metrics["abstention_reasons"]
    combo_meta = metrics.get("combo", {})
    assert combo_meta.get("decision", "").startswith("reject")
    assert "calibration_missing" in combo_meta.get("notes", [])


def test_pipeline_accepts_valid_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    eval_stats = {
        "status": "ok",
        "ev_ratio": 0.6,
        "payout_expected": 30.0,
        "roi": 0.35,
        "sharpe": 0.4,
    }

    _prepare_stubs(monkeypatch, eval_stats)
    inputs = _write_inputs(tmp_path)

    outdir = tmp_path / "out"
    result = pipeline_run.run_pipeline(
        h30=str(inputs["h30"]),
        h5=str(inputs["h5"]),
        stats_je=str(inputs["stats"]),
        partants=str(inputs["partants"]),
        gpi=str(inputs["gpi"]),
        outdir=str(outdir),
        calibration=DEFAULT_CALIBRATION,
    )

    metrics = result["metrics"]
    assert metrics["status"] in {"ok", "abstain"}
    assert "calibration_missing" not in metrics.get("abstention_reasons", [])
