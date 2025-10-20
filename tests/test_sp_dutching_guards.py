import json
from pathlib import Path
import yaml
import pandas as pd
import pytest
from scripts import runner_chain

def _setup_race_files(tmp_path: Path, race_id: str = "R1C1"):
    """Helper to create dummy files for _write_analysis."""
    analysis_dir = tmp_path / "analysis"
    race_dir = analysis_dir / race_id
    race_dir.mkdir(parents=True, exist_ok=True)
    (race_dir / "snapshot_H5.json").write_text(json.dumps({
        "payload": {
            "runners": [{"num": "1", "odds": 2.0}, {"num": "2", "odds": 3.0}]
        }
    }))
    (race_dir / "je_stats.csv").touch()
    (race_dir / "chronos.csv").touch()
    return analysis_dir, race_dir

def _write_gpi_config(tmp_path: Path, config: dict):
    """Helper to write a dummy gpi.yml."""
    gpi_path = tmp_path / "config"
    gpi_path.mkdir(exist_ok=True)
    gpi_file = gpi_path / "gpi.yml"
    gpi_file.write_text(yaml.dump(config))
    return gpi_file

def test_sp_guard_blocks_low_ev(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_chain, "USE_GCS", False)
    analysis_dir, race_dir = _setup_race_files(tmp_path)
    
    # Config with EV_MIN_SP = 30% of SP budget
    gpi_config = {"BUDGET_TOTAL": 5.0, "SP_RATIO": 1.0, "EV_MIN_SP": 0.3}
    _write_gpi_config(tmp_path, gpi_config)
    monkeypatch.setenv("GPI_CONFIG_FILE", str(tmp_path / "config/gpi.yml"))

    # Portfolio with EV of 1.0, on a 5.0 budget. EV is 20% of budget, so < 30%
    bets_df = pd.DataFrame({"EV (€)": [0.5, 0.5], "Stake (€)": [2.5, 2.5], "Gain brut (€)": [1.0, 1.0]})
    monkeypatch.setattr(runner_chain, "dutching_kelly_fractional", lambda **kwargs: bets_df)

    runner_chain._write_analysis(
        race_id="R1C1",
        base=analysis_dir,
        budget=5.0,
        ev_min=0.0,
        roi_min=0.0,
        mode="test",
        calibration=tmp_path / "cal.yaml",
        calibration_available=False,
    )

    result = json.loads((race_dir / "analysis.json").read_text())
    assert result["status"] == "aborted"
    assert "sp_policy_validation_failed" in result["reasons"]
    assert "EV_MIN_SP" in result["reasons"]

def test_sp_guard_blocks_low_roi(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_chain, "USE_GCS", False)
    analysis_dir, race_dir = _setup_race_files(tmp_path)
    
    # Config with ROI_MIN_SP = 50%
    gpi_config = {"ROI_MIN_SP": 0.5}
    _write_gpi_config(tmp_path, gpi_config)
    monkeypatch.setenv("GPI_CONFIG_FILE", str(tmp_path / "config/gpi.yml"))

    # Portfolio with ROI of 0.2, which is below the 0.5 threshold
    bets_df = pd.DataFrame({"EV (€)": [1.0], "Stake (€)": [5.0], "Gain brut (€)": [6.0]})
    monkeypatch.setattr(runner_chain, "dutching_kelly_fractional", lambda **kwargs: bets_df)

    runner_chain._write_analysis(
        race_id="R1C1",
        base=analysis_dir,
        budget=5.0,
        ev_min=0.0,
        roi_min=0.0,
        mode="test",
        calibration=tmp_path / "cal.yaml",
        calibration_available=False,
    )

    result = json.loads((race_dir / "analysis.json").read_text())
    assert result["status"] == "aborted"
    assert "sp_policy_validation_failed" in result["reasons"]
    assert "ROI_MIN_SP" in result["reasons"]