import datetime as dt
import json
from pathlib import Path

import pytest
import yaml

from runner_chain import RunnerPayload, _write_analysis


@pytest.fixture
def course_setup_single_candidate(tmp_path: Path) -> tuple[Path, Path]:
    """
    Crée une structure de course avec les fichiers obligatoires et des partants
    ne produisant qu'un seul candidat SP valide.
    """
    snap_dir = tmp_path / "snapshots"
    analysis_dir = tmp_path / "analyses"
    race_id = "R1C3"

    race_snap_dir = snap_dir / race_id
    race_analysis_dir = analysis_dir / race_id
    race_snap_dir.mkdir(parents=True, exist_ok=True)
    race_analysis_dir.mkdir(parents=True, exist_ok=True)

    # Crée des snapshots H30/H5 avec des données de partants
    partants_data = {
        "runners": [
            {"num": "1", "odds": 5.0},  # Le seul candidat valide (cote entre 2.5 et 7.0)
            {"num": "2", "odds": 1.5},  # Cote trop basse
            {"num": "3", "odds": 8.0},  # Cote trop haute
        ]
    }
    h30_snapshot = {"payload": {"runners": partants_data["runners"]}}
    h5_snapshot = {"payload": {"runners": partants_data["runners"]}}

    (race_snap_dir / "h30.json").write_text(json.dumps(h30_snapshot))
    (race_snap_dir / "h5.json").write_text(json.dumps(h5_snapshot))
    (race_snap_dir / "partants.json").write_text(json.dumps(partants_data))
    (race_snap_dir / "stats_je.json").write_text(json.dumps({}))
    (race_snap_dir / "chronos.csv").write_text("num,chrono,ok\n1,1.0,1\n")

    # Crée un dummy gpi.yml
    gpi_config = {
        "bankroll": {"stake_cap_per_race": 5.0, "split_sp": 0.6, "split_combos": 0.4},
        "kelly": {"base_fraction": 0.5, "single_leg_cap": 0.6},
        "ev": {"min_ev_sp_pct_budget": 0.0},
        "overround_bands": {"default_low_vol_max": 1.3}
    }
    (race_analysis_dir / "gpi.yml").write_text(yaml.dump(gpi_config))

    # Crée un dummy calibration.yaml
    (tmp_path / "calibration.yaml").write_text(yaml.dump({}))

    return snap_dir, analysis_dir


def test_analysis_produces_no_tickets_with_single_sp_candidate(course_setup_single_candidate):
    """
    Vérifie que le pipeline ne produit aucun ticket s'il n'y a qu'un seul
    candidat Simple Placé (SP), car le dutching nécessite au moins deux candidats.
    """
    snap_dir, analysis_dir = course_setup_single_candidate
    race_dir = analysis_dir / "R1C3"

    payload = RunnerPayload(
        id_course="202401010103",
        reunion="R1",
        course="C3",
        phase="H5",
        start_time=dt.datetime.now(),
        budget=5.0,
    )

    # Exécuter l'analyse (qui appelle le pipeline réel)
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

    # Le fichier p_finale.json doit exister mais ne contenir aucun ticket
    p_finale_path = race_dir / "out" / "p_finale.json"
    assert p_finale_path.exists()
    p_finale_data = json.loads(p_finale_path.read_text())

    assert p_finale_data.get("tickets") == []

    # Le rapport d'analyse doit également refléter l'absence de tickets
    analysis_path = race_dir / "analysis.json"
    assert analysis_path.exists()
    analysis_data = json.loads(analysis_path.read_text())

    metrics = analysis_data.get("metrics", {})
    assert metrics.get("tickets", {}).get("total") == 0
    assert metrics.get("tickets", {}).get("sp") == 0
