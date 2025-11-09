import json
from pathlib import Path
import datetime as dt

import pytest
import yaml

from runner_chain import _write_analysis, RunnerPayload


@pytest.fixture
def course_setup_roi(tmp_path: Path) -> tuple[Path, Path]:
    """Crée une structure de répertoires et les fichiers obligatoires pour l'analyse."""
    snap_dir = tmp_path / "snapshots"
    analysis_dir = tmp_path / "analyses"
    race_id = "R1C5"
    
    race_snap_dir = snap_dir / race_id
    race_analysis_dir = analysis_dir / race_id
    race_snap_dir.mkdir(parents=True, exist_ok=True)
    race_analysis_dir.mkdir(parents=True, exist_ok=True)

    # Crée les fichiers obligatoires
    (race_snap_dir / "h30.json").write_text(json.dumps({"payload": {}}))
    (race_snap_dir / "h5.json").write_text(json.dumps({"payload": {}}))
    (race_snap_dir / "partants.json").write_text(json.dumps({"runners": []}))
    (race_snap_dir / "stats_je.json").write_text(json.dumps({}))
    (race_snap_dir / "chronos.csv").write_text("num,chrono,ok\n1,1.0,1\n")

    # Crée un dummy gpi.yml
    (race_analysis_dir / "gpi.yml").write_text(yaml.dump({}))

    # Crée un dummy calibration.yaml
    (tmp_path / "calibration.yaml").write_text(yaml.dump({}))

    return snap_dir, analysis_dir


def test_write_analysis_passes_roi_min_to_pipeline(course_setup_roi, monkeypatch):
    """
    Vérifie que _write_analysis transmet correctement le paramètre roi_min
    en tant que roi_global à pipeline_run.run_pipeline.
    """
    snap_dir, analysis_dir = course_setup_roi
    
    captured_kwargs = {}

    def fake_run_pipeline(**kwargs):
        captured_kwargs.update(kwargs)
        # Crée un outdir pour que le reste de la fonction ne plante pas
        outdir = Path(kwargs.get("outdir", "dummy_out"))
        outdir.mkdir(exist_ok=True)
        return {"metrics": {"status": "ok"}, "outdir": str(outdir)}

    monkeypatch.setattr("runner_chain.pipeline_run.run_pipeline", fake_run_pipeline)

    payload = RunnerPayload(
        id_course="202401010105",
        reunion="R1",
        course="C5",
        phase="H5",
        start_time=dt.datetime.now(),
        budget=5.0,
    )
    
    test_roi_min = 0.08

    _write_analysis(
        payload,
        snap_dir,
        analysis_dir,
        budget=5.0,
        ev_min=0.1,
        roi_min=test_roi_min,
        mode="hminus5",
        calibration=Path(snap_dir.parent / "calibration.yaml"),
    )

    # Vérifie que la fonction mockée a été appelée
    assert captured_kwargs, "pipeline_run.run_pipeline was not called"
    
    # Vérifie que le paramètre roi_global a été passé avec la bonne valeur
    assert "roi_global" in captured_kwargs
    assert captured_kwargs["roi_global"] == test_roi_min
