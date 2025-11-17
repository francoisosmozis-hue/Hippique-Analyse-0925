import json
from pathlib import Path

import pytest
import yaml

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.overround import compute_overround_place
import pipeline_run
from src.hippique_orchestrator.pipeline_run import _load_simulate_ev
from tests.test_pipeline_smoke import partants_sample, GPI_YML


def test_estimate_overround_place_from_runners() -> None:
    runners = [
        {"odds_place": 2.0},
        {"odds_place": 2.5},
        {"odds_place": 3.5},
    ]
    expected = sum(1.0 / runner["odds_place"] for runner in runners)
    value = compute_overround_place([r["odds_place"] for r in runners])
    assert value == pytest.approx(expected)


def test_pipeline_blocks_combos_when_place_overround_high(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Setup snapshot with high place overround
    high_place_runners = [
        {"id": "1", "num": "1", "name": "A", "odds": 2.5, "odds_place": 2.0, "p_place": 0.5, "volatility": 0.5, "cote": 2.5},
        {"id": "2", "num": "2", "name": "B", "odds": 2.5, "odds_place": 2.0, "p_place": 0.5, "volatility": 0.5, "cote": 2.5},
        {"id": "3", "num": "3", "name": "C", "odds": 2.5, "odds_place": 2.0, "p_place": 0.5, "volatility": 0.5, "cote": 2.5},
    ]
    overround_place = sum(1.0 / r["odds_place"] for r in high_place_runners)  # 1.5

    snapshot_content = {
        "runners": high_place_runners,
        "market": {"overround_place": overround_place}
    }

    race_dir = tmp_path / "data" / "R1C1"
    race_dir.mkdir(parents=True, exist_ok=True)
    (race_dir / "snapshot_H5.json").write_text(json.dumps(snapshot_content))

    # Setup GPI config
    gpi_config = yaml.safe_load(GPI_YML)
    gpi_config['overround_max_exotics'] = 1.3  # lower than 1.5

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "gpi_v52.yml").write_text(yaml.dump(gpi_config))

    # Create a valid calibration file
    valid_calib_path = tmp_path / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    # Run pipeline
    result = pipeline_run.run_pipeline(
        reunion="R1",
        course="C1",
        phase="H5",
        budget=5.0,
        calibration_path=str(valid_calib_path),
        root_dir=tmp_path,
    )

    # Assert that no combo tickets are generated
    assert not any(t.get("type") == "TRIO" for t in result.get("tickets", []))
    assert result.get("abstain") is True
