import json
from pathlib import Path

import pytest

import pipeline_run
from tests.test_pipeline_smoke import (
    GPI_YML,
    partants_sample,
)


def test_pipeline_abstains_when_calibration_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Ensure the pipeline abstains if the calibration file is missing.
    """
    # Create the expected directory structure inside the temp path
    race_dir = tmp_path / "data" / "R1C1"
    race_dir.mkdir(parents=True, exist_ok=True)

    # Create a minimal snapshot file that the pipeline needs to start
    snapshot_content = {"runners": [{"num": "1", "p_place": 0.5, "cote": 3.0, "volatility": 0.5}]}
    (race_dir / "snapshot_H5.json").write_text(json.dumps(snapshot_content))

    # Create the GPI config file where the pipeline will look for it
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "gpi_v52.yml").write_text(GPI_YML)

    # Call the real function with correct arguments, including root_dir
    result = pipeline_run.run_pipeline(
        reunion="R1",
        course="C1",
        phase="H5",
        budget=5.0,
        calibration_path=str(tmp_path / "missing_calibration.yaml"), # This file does not exist
        root_dir=tmp_path,
    )

    metrics = result.get("metrics", {})
    assert metrics.get("status") == "insufficient_data"
    assert metrics.get("reason") == "missing_calibration"


def test_pipeline_accepts_valid_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Ensure the pipeline runs with a valid calibration file.
    """
    # Create the expected directory structure inside the temp path
    race_dir = tmp_path / "data" / "R1C1"
    race_dir.mkdir(parents=True, exist_ok=True)

    # Use a more complete snapshot for this test
    snapshot_content = partants_sample()
    (race_dir / "snapshot_H5.json").write_text(json.dumps(snapshot_content))

    # Create the GPI config file
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "gpi_v52.yml").write_text(GPI_YML)

    # Create a valid calibration file
    valid_calib_path = tmp_path / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    # Call the real function with correct arguments
    result = pipeline_run.run_pipeline(
        reunion="R1",
        course="C1",
        phase="H5",
        budget=5.0,
        calibration_path=str(valid_calib_path),
        root_dir=tmp_path,
    )

    # Check that the pipeline did not abstain for calibration reasons
    assert result.get("metrics", {}).get("reason") != "missing_calibration"
    assert result.get("abstain") is False
