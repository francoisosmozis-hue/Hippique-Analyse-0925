import json
from pathlib import Path
import datetime as dt

import pytest
import yaml

from runner_chain import _write_analysis, RunnerPayload


@pytest.fixture
def course_setup(tmp_path: Path) -> tuple[Path, Path]:
    """Crée une structure de répertoires et les fichiers obligatoires pour l'analyse."""
    snap_dir = tmp_path / "snapshots"
    analysis_dir = tmp_path / "analyses"
    race_id = "R1C1"
    
    # Crée les répertoires de course
    (snap_dir / race_id).mkdir(parents=True, exist_ok=True)
    (analysis_dir / race_id).mkdir(parents=True, exist_ok=True)

    # Crée les fichiers obligatoires vides mais valides
    (snap_dir / race_id / "h30.json").write_text(json.dumps({"payload": {}}))
    (snap_dir / race_id / "h5.json").write_text(json.dumps({"payload": {}}))
    (snap_dir / race_id / "partants.json").write_text(json.dumps({"runners": []}))

    # Crée un dummy gpi.yml
    gpi_config = {"overround_bands": {"default_low_vol_max": 1.3}}
    (analysis_dir / race_id / "gpi.yml").write_text(yaml.dump(gpi_config))

    # Crée un dummy calibration.yaml
    (tmp_path / "calibration.yaml").write_text(yaml.dump({}))

    return snap_dir, analysis_dir


def test_analysis_disables_exotics_when_je_missing(course_setup, monkeypatch):
    """Vérifie que l'analyse désactive les exotiques si je_stats.json est manquant."""
    snap_dir, analysis_dir = course_setup
    race_id = "R1C1"
    race_dir = analysis_dir / race_id

    # Fournir chronos.csv mais pas stats_je.json
    (snap_dir / race_id / "chronos.csv").write_text("num,chrono,ok\n1,1.0,1\n")

    # Simuler le pipeline pour éviter une exécution réelle complexe
    def fake_run_pipeline(**kwargs):
        return {"metrics": {"status": "ok"}, "outdir": kwargs.get("outdir")}
    monkeypatch.setattr("runner_chain.pipeline_run.run_pipeline", fake_run_pipeline)

    payload = RunnerPayload(
        id_course="202401010101",
        reunion="R1",
        course="C1",
        phase="H5",
        start_time=dt.datetime.now(),
        budget=5.0,
    )

    _write_analysis(
        payload,
        snap_dir,
        analysis_dir,
        budget=5.0,
        ev_min=0.1,
        roi_min=0.1,
        mode="hminus5",
        calibration=Path(snap_dir.parent / "calibration.yaml"),
    )

    analysis_path = race_dir / "analysis.json"
    assert analysis_path.exists()
    analysis_data = json.loads(analysis_path.read_text())

    assert analysis_data["status"] == "ok"
    assert analysis_data["exotics_disabled"] is True
    assert "exotics disabled: stats_je missing" in analysis_data["notes"]


def test_analysis_disables_exotics_when_chronos_missing(course_setup, monkeypatch):
    """Vérifie que l'analyse désactive les exotiques si chronos.csv est manquant."""
    snap_dir, analysis_dir = course_setup
    race_id = "R1C1"
    race_dir = analysis_dir / race_id

    # Fournir stats_je.json mais pas chronos.csv
    (snap_dir / race_id / "stats_je.json").write_text(json.dumps({}))

    # Simuler le pipeline
    def fake_run_pipeline(**kwargs):
        return {"metrics": {"status": "ok"}, "outdir": kwargs.get("outdir")}
    monkeypatch.setattr("runner_chain.pipeline_run.run_pipeline", fake_run_pipeline)

    payload = RunnerPayload(
        id_course="202401010101",
        reunion="R1",
        course="C1",
        phase="H5",
        start_time=dt.datetime.now(),
        budget=5.0,
    )

    _write_analysis(
        payload,
        snap_dir,
        analysis_dir,
        budget=5.0,
        ev_min=0.1,
        roi_min=0.1,
        mode="hminus5",
        calibration=Path(snap_dir.parent / "calibration.yaml"),
    )

    analysis_path = race_dir / "analysis.json"
    assert analysis_path.exists()
    analysis_data = json.loads(analysis_path.read_text())

    assert analysis_data["status"] == "ok"
    assert analysis_data["exotics_disabled"] is True
    assert "exotics disabled: chronos missing" in analysis_data["notes"]
