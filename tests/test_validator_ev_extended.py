
import sys
import os
import pytest
from pathlib import Path
import json
import yaml
import subprocess

# Ensure the source directory is in the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hippique_orchestrator.validator_ev import (
    validate_budget,
    ValidationError,
    validate,
    _readme_has_roi_sp,
    must_have,
    _load_partants,
    _load_odds
)

# --- Tests for validate_budget ---

def test_validate_budget_success():
    stakes = {"1": 10.0, "2": 15.0}
    assert validate_budget(stakes, budget_cap=30.0, max_vol_per_horse=0.6)

def test_validate_budget_exceeds_total_cap():
    stakes = {"1": 10.0, "2": 15.0, "3": 10.0}
    with pytest.raises(ValidationError, match="Budget cap exceeded"):
        validate_budget(stakes, budget_cap=30.0, max_vol_per_horse=0.6)

def test_validate_budget_exceeds_horse_cap():
    stakes = {"1": 20.0, "2": 5.0}
    with pytest.raises(ValidationError, match="Stake cap exceeded for 1"):
        validate_budget(stakes, budget_cap=30.0, max_vol_per_horse=0.5)

# --- Tests for validate ---

def create_snapshot(num_runners, odds_prefix="", missing_odds_for=None, invalid_odds_for=None, missing_je_for=None):
    runners = []
    for i in range(1, num_runners + 1):
        runner_id = f"{odds_prefix}{i}"
        runner = {"id": runner_id, "name": f"Horse {runner_id}"}
        if missing_odds_for != i:
            runner["odds"] = "2.0" if invalid_odds_for != i else "invalid"
        if missing_je_for != i:
            runner["je_stats"] = {"j_win": 10, "e_win": 15}
        runners.append(runner)
    return {"runners": runners}

def test_validate_success():
    h30 = create_snapshot(8)
    h5 = create_snapshot(8)
    assert validate(h30, h5, allow_je_na=False)

def test_validate_inconsistent_runners():
    h30 = create_snapshot(8)
    h5 = create_snapshot(7)
    with pytest.raises(ValueError, match="Partants incohérents"):
        validate(h30, h5, allow_je_na=False)

def test_validate_missing_odds():
    h30 = create_snapshot(8)
    h5 = create_snapshot(8, missing_odds_for=3)
    with pytest.raises(ValueError, match="Cotes manquantes H-5 pour Horse 3"):
        validate(h30, h5, allow_je_na=False)

def test_validate_invalid_odds_non_numeric():
    h30 = create_snapshot(8)
    h5 = create_snapshot(8, invalid_odds_for=4)
    with pytest.raises(ValueError, match="Cote non numérique H-5 pour Horse 4"):
        validate(h30, h5, allow_je_na=False)

def test_validate_invalid_odds_too_low():
    h30 = create_snapshot(8)
    h5 = create_snapshot(8)
    h5["runners"][2]["odds"] = "1.01"
    with pytest.raises(ValueError, match="Cote invalide H-5 pour Horse 3"):
        validate(h30, h5, allow_je_na=False)

def test_validate_missing_je_stats_fails_when_required():
    h30 = create_snapshot(8)
    h5 = create_snapshot(8, missing_je_for=5)
    with pytest.raises(ValueError, match="Stats J/E manquantes: Horse 5"):
        validate(h30, h5, allow_je_na=False)

def test_validate_missing_je_stats_passes_when_allowed():
    h30 = create_snapshot(8)
    h5 = create_snapshot(8, missing_je_for=5)
    assert validate(h30, h5, allow_je_na=True)

# --- Tests for _readme_has_roi_sp ---

def test_readme_has_roi_sp_success(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("Le ROI_SP est de 25%. Un bon rendement.")
    os.chdir(tmp_path)
    assert _readme_has_roi_sp(target=0.20)
    assert _readme_has_roi_sp(target=0.25)

def test_readme_has_roi_sp_no_match(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("Le retour sur investissement est bon.")
    os.chdir(tmp_path)
    assert not _readme_has_roi_sp(target=0.20)

def test_readme_has_roi_sp_value_too_low(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("Objectif de ROI SP: 15%")
    os.chdir(tmp_path)
    assert not _readme_has_roi_sp(target=0.20)

def test_readme_missing_is_true(tmp_path):
    os.chdir(tmp_path)
    assert _readme_has_roi_sp(target=0.20)

# --- Tests for must_have ---

def test_must_have_raises_error():
    with pytest.raises(RuntimeError, match="Value must be present"):
        must_have(None, "Value must be present")
    with pytest.raises(RuntimeError, match="Value must be present"):
        must_have(0, "Value must be present")

def test_must_have_returns_value():
    assert must_have(1, "msg") == 1
    assert must_have("hello", "msg") == "hello"

# --- Tests for file loaders ---

def test_load_partants_from_list(tmp_path):
    p_file = tmp_path / "partants.json"
    p_file.write_text(json.dumps([{"id": 1}, {"id": 2}]))
    partants = _load_partants(p_file)
    assert len(partants) == 2
    assert partants[0]["id"] == 1

def test_load_partants_from_dict(tmp_path):
    p_file = tmp_path / "partants.json"
    p_file.write_text(json.dumps({"runners": [{"id": 1}, {"id": 2}]}))
    partants = _load_partants(p_file)
    assert len(partants) == 2
    assert partants[1]["id"] == 2

def test_load_partants_invalid_format_raises_error(tmp_path):
    p_file = tmp_path / "partants.json"
    p_file.write_text(json.dumps({"wrong_key": []}))
    with pytest.raises(ValueError, match="Format partants invalide"):
        _load_partants(p_file)

def test_load_odds_from_dict(tmp_path):
    o_file = tmp_path / "odds.json"
    o_file.write_text(json.dumps({"1": 2.5, "2": "3,5"}))
    odds = _load_odds(o_file)
    assert len(odds) == 2
    assert odds["1"] == 2.5
    assert odds["2"] == 3.5

def test_load_odds_from_runners_list(tmp_path):
    o_file = tmp_path / "snapshot_H-5.json"
    o_file.write_text(json.dumps({"runners": [{"id": "1", "cote": "5.0"}, {"num": 2, "odds": 4.0}]}))
    odds = _load_odds(o_file)
    assert len(odds) == 2
    assert odds["1"] == 5.0
    assert odds["2"] == 4.0

def test_load_odds_empty_file_raises_error(tmp_path):

    o_file = tmp_path / "odds.json"

    o_file.write_text(json.dumps({}))

    with pytest.raises(ValueError, match="Impossible d'extraire les cotes"):

        _load_odds(o_file)



# --- CLI Integration Tests ---



def run_cli(*args):

    """Helper to run the validator CLI script via subprocess."""

    result = subprocess.run(

        [sys.executable, "-m", "hippique_orchestrator.validator_ev", *args],

        check=False,

        capture_output=True,

        text=True,

        encoding="utf-8",

    )

    return result.returncode, json.loads(result.stdout.strip()) if result.stdout else {}



def setup_race_files(tmp_path, partants_data, odds_data, stats_data=None, config_data=None, phase="H5"):

    """Create artefact files in a temp directory."""

    (tmp_path / "partants.json").write_text(json.dumps(partants_data))

    

    odds_filename = "h5.json" if phase == "H5" else "h30.json"

    (tmp_path / odds_filename).write_text(json.dumps(odds_data))



    if stats_data:

        (tmp_path / "stats_je.json").write_text(json.dumps(stats_data))

    if config_data:

        (tmp_path / "gpi.yml").write_text(yaml.dump(config_data))



def test_cli_success_with_artefacts_dir(tmp_path):

    partants = {"runners": [{"id": str(i)} for i in range(1, 7)]}

    odds = {str(i): 2.0 for i in range(1, 7)}

    stats = {"coverage": 90.0}

    setup_race_files(tmp_path, partants, odds, stats)



    return_code, summary = run_cli("--artefacts", str(tmp_path))

    

    assert return_code == 0

    assert summary["ok"] is True



def test_cli_discovery_with_rc(tmp_path):

    rc_dir = tmp_path / "R1C1"

    rc_dir.mkdir()

    partants = {"runners": [{"id": str(i)} for i in range(1, 8)]}

    odds = {str(i): 3.0 for i in range(1, 8)}

    stats = {"coverage": 100}

    setup_race_files(rc_dir, partants, odds, stats)



    return_code, summary = run_cli("--base-dir", str(tmp_path), "--reunion", "R1", "--course", "C1")

    

    assert return_code == 0

    assert summary["ok"] is True



def test_cli_file_not_found_error(tmp_path):

    return_code, summary = run_cli("--artefacts", str(tmp_path))



    assert return_code == 1

    assert summary["ok"] is False

    assert "Fichier non trouvé" in summary["reason"]



def test_cli_value_error_on_malformed_json(tmp_path):

    (tmp_path / "partants.json").write_text("not json")

    (tmp_path / "h5.json").write_text(json.dumps({"1": 2.0}))

    

    return_code, summary = run_cli("--artefacts", str(tmp_path))



    assert return_code == 1

    assert summary["ok"] is False

    assert "Erreur de valeur" in summary["reason"]



def test_cli_allow_je_na_flag(tmp_path):

    partants = {"runners": [{"id": str(i)} for i in range(1, 7)]}

    odds = {str(i): 2.0 for i in range(1, 7)}

    # No stats file

    setup_race_files(tmp_path, partants, odds, stats_data=None)



    # Should fail without the flag

    return_code, summary = run_cli("--artefacts", str(tmp_path))

    assert return_code == 1

    assert "Couverture J/E" in summary.get("reason", "")



    # Should pass with the flag

    return_code_allow, summary_allow = run_cli("--artefacts", str(tmp_path), "--allow-je-na")

    assert return_code_allow == 0

    assert summary_allow["ok"] is True



def test_cli_uses_explicit_config(tmp_path):

    rc_dir = tmp_path / "R1C1"

    rc_dir.mkdir()

    partants = {"runners": [{"id": str(i)} for i in range(1, 7)]}

    odds = {str(i): 2.0 for i in range(1, 7)}

    # Missing JE stats, should fail with default config

    setup_race_files(rc_dir, partants, odds, stats_data={"coverage": 10})

    

    config_path = tmp_path / "custom_config.yml"

    config_path.write_text(yaml.dump({"ALLOW_JE_NA": True}))



    # This should pass because the custom config is used

    return_code, summary = run_cli(

        "--base-dir", str(tmp_path), "--reunion", "R1", "--course", "C1", "--config", str(config_path)

    )

    assert return_code == 0

    assert summary["ok"] is True
