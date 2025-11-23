import json
from pathlib import Path

import pytest
import yaml

from src.pipeline_run import api_entrypoint, run_pipeline


@pytest.fixture
def course_with_high_overround(tmp_path: Path) -> Path:
    """Crée une configuration de course avec un overround élevé."""
    race_dir = tmp_path / "data" / "R1C1"
    race_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = race_dir / "snapshot_H5.json"

    # Overround = 1/1.5 + 1/1.5 = 0.666... + 0.666... = 1.333... > 1.3
    snapshot_data = {
        "runners": [
            {"num": "1", "cote": 1.5, "p_place": 0.6, "volatility": 0.1},
            {"num": "2", "cote": 1.5, "p_place": 0.6, "volatility": 0.1},
        ],
        "market": {
            "overround_place": 1.34
        },
    }
    snapshot_path.write_text(json.dumps(snapshot_data))

    gpi_config = {
        "overround_max_exotics": 1.3,
        "roi_min_sp": 0.1,
        "tickets_max": 2,
        "tickets": {
            "sp_dutching": {
                "odds_range": [1.0, 100.0],
                "legs_min": 1,
                "legs_max": 5,
                "kelly_frac": 0.1
            }
        }
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "gpi_v52.yml").write_text(yaml.dump(gpi_config))

    return tmp_path

def test_pipeline_rejects_on_high_overround(course_with_high_overround: Path) -> None:
    """
    Vérifie que le pipeline rejette la course si l'overround du marché
    dépasse le seuil configuré.
    """
    # Create a valid calibration file
    valid_calib_path = course_with_high_overround / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    # Appeler le pipeline avec les chemins des fichiers de test
    result = run_pipeline(
        reunion="R1",
        course="C1",
        phase="H5",
        budget=5.0,
        calibration_path=str(valid_calib_path),
        root_dir=course_with_high_overround,
    )

    # La raison de l'abstention doit être l'overround élevé
    assert result.get("abstain") is True
    assert "No valid tickets found after applying guardrails." in result.get("message", "")
    # Vérifier que p_finale.json ne contient aucun ticket
    analysis_path = course_with_high_overround / "data" / "R1C1" / "analysis_H5.json"
    assert analysis_path.exists()
    analysis_data = json.loads(analysis_path.read_text())
    assert analysis_data.get("tickets") == []


@pytest.fixture
def course_with_no_runners(tmp_path: Path) -> Path:
    """Crée une configuration de course avec un snapshot sans runners."""
    race_dir = tmp_path / "data" / "R1C3"
    race_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = race_dir / "snapshot_H5.json"
    snapshot_path.write_text(json.dumps({"runners": []}))

    gpi_config = {"overround_max_exotics": 1.3, "roi_min_sp": 0.1}
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "gpi_v52.yml").write_text(yaml.dump(gpi_config))

    return tmp_path


def test_pipeline_abstains_with_no_runners(course_with_no_runners: Path) -> None:
    """
    Vérifie que le pipeline s'abstient si le snapshot ne contient aucun runner.
    """
    valid_calib_path = course_with_no_runners / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    result = run_pipeline(
        reunion="R1",
        course="C3",
        phase="H5",
        budget=5.0,
        calibration_path=str(valid_calib_path),
        root_dir=course_with_no_runners,
    )

    assert result.get("abstain") is True
    assert result.get("message") == "No runners found in snapshot"
    assert result.get("tickets") == []


@pytest.fixture
def course_for_calibration_test(tmp_path: Path) -> Path:
    """Crée une configuration de course valide pour tester la calibration."""
    race_dir = tmp_path / "data" / "R1C4"
    race_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = race_dir / "snapshot_H5.json"
    snapshot_data = {
        "runners": [{"num": "1", "cote": 3.0, "p_place": 0.5, "volatility": 0.2}],
        "market": {"overround_place": 1.2},
    }
    snapshot_path.write_text(json.dumps(snapshot_data))

    gpi_config = {
        "overround_max_exotics": 1.3,
        "roi_min_sp": 0.1,
        "tickets_max": 5,
        "budget_cap_eur": 100,
        "max_vol_per_horse": 0.8,
        "tickets": {
            "sp_dutching": {
                "odds_range": [1.0, 10.0], "legs_min": 1, "legs_max": 2, "kelly_frac": 0.1
            }
        }
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "gpi_v52.yml").write_text(yaml.dump(gpi_config))

    return tmp_path


def test_pipeline_abstains_when_calibration_missing(course_for_calibration_test: Path) -> None:
    """
    Vérifie que le pipeline s'abstient si le fichier de calibration est manquant.
    """
    missing_calib_path = course_for_calibration_test / "non_existent_calib.yaml"

    result = run_pipeline(
        reunion="R1",
        course="C4",
        phase="H5",
        budget=5.0,
        calibration_path=str(missing_calib_path),
        root_dir=course_for_calibration_test,
    )

    expected = {
        "metrics": {"status": "insufficient_data", "reason": "missing_calibration"},
        "tickets": [],
    }
    assert result == expected


def test_pipeline_generates_sp_dutching_ticket(course_for_calibration_test: Path) -> None:
    """
    Vérifie que le pipeline génère un ticket SP_DUTCHING lorsqu'un candidat valide est présent.
    """
    # Utilise la même fixture mais avec un fichier de calibration valide
    valid_calib_path = course_for_calibration_test / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    result = run_pipeline(
        reunion="R1",
        course="C4",
        phase="H5",
        budget=10.0,
        calibration_path=str(valid_calib_path),
        root_dir=course_for_calibration_test,
    )

    assert result.get("abstain") is False
    assert result.get("message") == ""
    assert len(result["tickets"]) == 1

    ticket = result["tickets"][0]
    assert ticket["type"] == "SP_DUTCHING"
    assert ticket["stake"] > 0
    assert ticket["roi_est"] > 0
    assert result["roi_global_est"] > 0
    assert "1" in ticket["horses"]


def test_pipeline_respects_ticket_cap(tmp_path: Path) -> None:
    """
    Vérifie que le pipeline ne génère pas plus de tickets que la limite
    configurée dans `tickets_max`.
    """
    race_dir = tmp_path / "data" / "R1C5"
    race_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = race_dir / "snapshot_H5.json"
    # 3 valid candidates
    snapshot_data = {
        "runners": [
            {"num": "1", "cote": 4.0, "p_place": 0.4, "volatility": 0.1},
            {"num": "2", "cote": 5.0, "p_place": 0.3, "volatility": 0.1},
            {"num": "3", "cote": 6.0, "p_place": 0.25, "volatility": 0.1},
        ],
        "market": {"overround_place": 1.2},
    }
    snapshot_path.write_text(json.dumps(snapshot_data))

    gpi_config = {
        "overround_max_exotics": 1.3, "roi_min_sp": 0.1, "tickets_max": 1, # Cap tickets to 1
        "budget_cap_eur": 100, "max_vol_per_horse": 0.8,
        "tickets": {
            "sp_dutching": {
                "odds_range": [1.0, 10.0], "legs_min": 1, "legs_max": 5, "kelly_frac": 0.1
            }
        }
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "gpi_v52.yml").write_text(yaml.dump(gpi_config))

    valid_calib_path = tmp_path / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    result = run_pipeline(
        reunion="R1", course="C5", phase="H5", budget=20.0,
        calibration_path=str(valid_calib_path), root_dir=tmp_path
    )

    assert result.get("abstain") is False
    assert len(result["tickets"]) == 1


def test_pipeline_scales_stake_to_budget(course_for_calibration_test: Path) -> None:
    """
    Vérifie que le pipeline met à l'échelle la mise du ticket pour respecter le budget.
    """
    valid_calib_path = course_for_calibration_test / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    # Le budget est très bas, forçant la mise à l'échelle
    low_budget = 1.0
    result = run_pipeline(
        reunion="R1",
        course="C4",
        phase="H5",
        budget=low_budget,
        calibration_path=str(valid_calib_path),
        root_dir=course_for_calibration_test,
    )

    assert result.get("abstain") is False
    assert len(result["tickets"]) == 1
    # La mise du ticket doit être plafonnée au budget
    assert result["tickets"][0]["stake"] <= low_budget


@pytest.fixture
def course_for_combo_test(tmp_path: Path) -> Path:
    """Crée une configuration de course valide pour générer un ticket SP et un combo."""
    race_dir = tmp_path / "data" / "R1C6"
    race_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = race_dir / "snapshot_H5.json"
    snapshot_data = {
        "runners": [
            {"num": "1", "cote": 4.0, "p_place": 0.4, "volatility": 0.1}, # SP cand
            {"num": "2", "cote": 5.0, "p_place": 0.3, "volatility": 0.1},
            {"num": "3", "cote": 6.0, "p_place": 0.25, "volatility": 0.1},
            {"num": "4", "cote": 10.0, "p_place": 0.1, "volatility": 0.1},
        ],
        "market": {"overround_place": 1.2},
    }
    snapshot_path.write_text(json.dumps(snapshot_data))

    gpi_config = {
        "overround_max_exotics": 1.3, "roi_min_sp": 0.1, "tickets_max": 5,
        "budget_cap_eur": 100, "max_vol_per_horse": 0.8,
        "ev_min_combo": 0.2, "payout_min_combo": 10,
        "tickets": {
            "sp_dutching": {
                "odds_range": [1.0, 10.0], "legs_min": 1, "legs_max": 5, "kelly_frac": 0.1
            }
        }
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "gpi_v52.yml").write_text(yaml.dump(gpi_config))

    return tmp_path


def test_pipeline_generates_sp_and_combo_tickets(course_for_combo_test: Path, mocker) -> None:
    """
    Vérifie que le pipeline génère un ticket SP et un ticket Combo lorsque les
    conditions sont remplies.
    """
    # Mock l'évaluation du combo pour qu'elle soit réussie
    mocker.patch(
        "src.pipeline_run.evaluate_combo",
        return_value={"status": "ok", "roi": 0.5, "payout_expected": 25.0}
    )

    valid_calib_path = course_for_combo_test / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    result = run_pipeline(
        reunion="R1", course="C6", phase="H5", budget=20.0,
        calibration_path=str(valid_calib_path), root_dir=course_for_combo_test
    )

    assert result.get("abstain") is False
    assert len(result["tickets"]) == 2
    ticket_types = {t["type"] for t in result["tickets"]}
    assert "SP_DUTCHING" in ticket_types
    assert "TRIO" in ticket_types


def test_pipeline_abstains_when_snapshot_missing(tmp_path: Path) -> None:
    """
    Vérifie que le pipeline s'abstient si le fichier snapshot est manquant.
    """
    # Créer une configuration de base sans snapshot
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "gpi_v52.yml").write_text(yaml.dump({
        "overround_max_exotics": 1.3,
        "roi_min_sp": 0.1,
    }))

    # Créer un fichier de calibration valide
    valid_calib_path = tmp_path / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    # Appeler le pipeline pour une course où le snapshot n'existe pas
    result = run_pipeline(
        reunion="R1",
        course="C2",
        phase="H5",
        budget=5.0,
        calibration_path=str(valid_calib_path),
        root_dir=tmp_path,
    )

    # Le pipeline doit s'abstenir car le snapshot est introuvable
    assert result.get("abstain") is True
    assert "Snapshot not found" in result.get("message", "")
    assert result.get("tickets") == []

def test_api_entrypoint_missing_fields():
    """Tests that the api_entrypoint raises ValueError for incomplete payloads."""
    with pytest.raises(ValueError, match="Missing required payload fields: reunion, course, phase"):
        api_entrypoint({"reunion": "R1", "phase": "H5"}) # Missing "course"

@pytest.fixture
def course_with_low_roi_candidate(tmp_path: Path) -> Path:
    """Crée une configuration avec un candidat SP valide mais un ROI global faible."""
    race_dir = tmp_path / "data" / "R1C7"
    race_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = race_dir / "snapshot_H5.json"

    # ROI = (0.3 * 3.5) - 1 = 0.05, which is > 0 but < 0.1
    snapshot_data = {
        "runners": [
            {"num": "1", "cote": 3.5, "p_place": 0.3, "volatility": 0.1},
        ],
        "market": {"overround_place": 1.2},
    }
    snapshot_path.write_text(json.dumps(snapshot_data))

    gpi_config = {
        "overround_max_exotics": 1.3,
        "roi_min_sp": 0.1, # ROI threshold
        "tickets_max": 5,
        "budget_cap_eur": 100,
        "max_vol_per_horse": 0.8,
        "tickets": {
            "sp_dutching": {
                "odds_range": [1.0, 10.0], "legs_min": 1, "legs_max": 2, "kelly_frac": 0.1
            }
        }
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "gpi_v52.yml").write_text(yaml.dump(gpi_config))

    return tmp_path

def test_pipeline_abstains_on_low_global_roi(course_with_low_roi_candidate: Path) -> None:
    """
    Vérifie que le pipeline s'abstient si le ROI global estimé est inférieur au seuil.
    """
    valid_calib_path = course_with_low_roi_candidate / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    result = run_pipeline(
        reunion="R1",
        course="C7",
        phase="H5",
        budget=10.0,
        calibration_path=str(valid_calib_path),
        root_dir=course_with_low_roi_candidate,
    )

    assert result["abstain"] is True
    assert "No valid tickets found" in result["message"]

    assert result["tickets"] == []
    assert result["roi_global_est"] == 0

@pytest.fixture
def course_with_missing_runner_data(tmp_path: Path) -> Path:
    """Crée une configuration avec un runner valide et un avec des données manquantes."""
    race_dir = tmp_path / "data" / "R1C8"
    race_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = race_dir / "snapshot_H5.json"

    snapshot_data = {
        "runners": [
            {"num": "1", "cote": 4.0, "p_place": 0.4, "volatility": 0.1}, # Valid
            {"num": "2", "cote": 5.0, "volatility": 0.1}, # Missing p_place
        ],
        "market": {"overround_place": 1.2},
    }
    snapshot_path.write_text(json.dumps(snapshot_data))

    gpi_config = {
        "overround_max_exotics": 1.3,
        "roi_min_sp": 0.1,
        "tickets_max": 5,
        "budget_cap_eur": 100,
        "max_vol_per_horse": 0.8,
        "tickets": {
            "sp_dutching": {
                "odds_range": [1.0, 10.0], "legs_min": 1, "legs_max": 2, "kelly_frac": 0.1
            }
        }
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "gpi_v52.yml").write_text(yaml.dump(gpi_config))

    return tmp_path

def test_pipeline_filters_runners_with_missing_data(course_with_missing_runner_data: Path) -> None:
    """
    Vérifie que le pipeline ignore les runners avec des données manquantes.
    """
    valid_calib_path = course_with_missing_runner_data / "calib.yaml"
    valid_calib_path.write_text("version: 1")

    result = run_pipeline(
        reunion="R1",
        course="C8",
        phase="H5",
        budget=10.0,
        calibration_path=str(valid_calib_path),
        root_dir=course_with_missing_runner_data,
    )

    assert result["abstain"] is False
    assert len(result["tickets"]) == 1
    assert result["tickets"][0]["type"] == "SP_DUTCHING"
    # The ticket should only contain the valid horse
    assert result["tickets"][0]["horses"] == ["1"]
