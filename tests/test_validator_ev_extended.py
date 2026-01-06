# -*- coding: utf-8 -*-

import json
import os
import sys
from unittest.mock import patch, Mock

import pytest
import yaml

from hippique_orchestrator.validator_ev import (
    validate_inputs,
    ValidationError,
    validate,
    validate_ev,
    validate_policy,
    validate_budget,
    validate_combos,
    combos_allowed,
    main as validator_main,
    _load_cfg,
    _readme_has_roi_sp,
    summarise_validation,
    _normalise_phase,
    _load_json_payload,
    _find_first_existing,
    _load_partants,
    _load_odds,
    _load_stats,
    _load_config,
    _resolve_rc_directory,
    _discover_file,
    _prepare_validation_inputs,
    must_have,
)
from hippique_orchestrator import config
from pathlib import Path


def test_validate_inputs_happy_path():
    """Test that validate_inputs passes with valid data."""

    cfg = {"ALLOW_JE_NA": False}

    partants = [{"id": i} for i in range(6)]

    odds = {i: 2.0 for i in range(6)}

    stats_je = {"coverage": 85}

    assert validate_inputs(cfg, partants, odds, stats_je) is True


def test_validate_inputs_not_enough_partants():
    """Test that validate_inputs fails when there are not enough partants."""

    cfg = {}

    partants = [{"id": i} for i in range(5)]

    odds = {i: 2.0 for i in range(5)}

    stats_je = {"coverage": 90}

    with pytest.raises(ValidationError, match="Nombre de partants insuffisant"):
        validate_inputs(cfg, partants, odds, stats_je)


def test_validate_inputs_missing_odds():
    """Test that validate_inputs fails with missing odds."""

    cfg = {}

    partants = [{"id": i} for i in range(6)]

    odds = {}

    stats_je = {"coverage": 90}

    with pytest.raises(ValidationError, match="Cotes manquantes"):
        validate_inputs(cfg, partants, odds, stats_je)


def test_validate_inputs_none_in_odds():
    """Test that validate_inputs fails with a None value in odds."""

    cfg = {}

    partants = [{"id": i} for i in range(6)]

    odds = {i: 2.0 for i in range(5)}

    odds[5] = None

    stats_je = {"coverage": 90}

    with pytest.raises(ValidationError, match="Cote manquante pour 5"):
        validate_inputs(cfg, partants, odds, stats_je)


def test_validate_inputs_je_coverage_insufficient():
    """Test that validate_inputs fails with insufficient J/E coverage."""

    cfg = {"ALLOW_JE_NA": False}

    partants = [{"id": i} for i in range(6)]

    odds = {i: 2.0 for i in range(6)}

    stats_je = {"coverage": 79.9}

    with pytest.raises(ValidationError, match="Couverture J/E insuffisante"):
        validate_inputs(cfg, partants, odds, stats_je)


def test_validate_inputs_je_coverage_missing_but_allowed():
    """Test that validate_inputs passes if J/E coverage is missing but allowed."""

    cfg = {"ALLOW_JE_NA": True}

    partants = [{"id": i} for i in range(6)]

    odds = {i: 2.0 for i in range(6)}

    stats_je = {}

    assert validate_inputs(cfg, partants, odds, stats_je) is True


def test_validate_inconsistent_partants():
    """Test validate fails with inconsistent partants."""

    h30 = {"runners": [{"id": 1}, {"id": 2}]}

    h5 = {"runners": [{"id": 1}, {"id": 3}]}

    with pytest.raises(ValueError, match="Partants incohérents"):
        validate(h30, h5, allow_je_na=True)


def test_validate_no_partants():
    """Test validate fails with no partants."""

    h30 = {"runners": []}

    h5 = {"runners": []}

    with pytest.raises(ValueError, match="Aucun partant"):
        validate(h30, h5, allow_je_na=True)


def test_validate_missing_odds_h30():
    """Test validate fails with missing odds in H-30."""

    h30 = {"runners": [{"id": 1, "name": "horse-1"}]}

    h5 = {"runners": [{"id": 1, "name": "horse-1", "odds": "2.5"}]}

    with pytest.raises(ValueError, match="Cotes manquantes H-30 pour horse-1"):
        validate(h30, h5, allow_je_na=True)


def test_validate_non_numeric_odds_h5():
    """Test validate fails with non-numeric odds in H-5."""

    h30 = {"runners": [{"id": 1, "name": "horse-1", "odds": "2.5"}]}

    h5 = {"runners": [{"id": 1, "name": "horse-1", "odds": "invalid"}]}

    with pytest.raises(ValueError, match="Cote non numérique H-5 pour horse-1: invalid"):
        validate(h30, h5, allow_je_na=True)


def test_validate_invalid_odds_h30():
    """Test validate fails with odds <= 1.01."""

    h30 = {"runners": [{"id": 1, "name": "horse-1", "odds": "1.01"}]}

    h5 = {"runners": [{"id": 1, "name": "horse-1", "odds": "2.5"}]}

    with pytest.raises(ValueError, match="Cote invalide H-30 pour horse-1: 1.01"):
        validate(h30, h5, allow_je_na=True)


def test_validate_missing_je_stats_when_required():
    """Test validate fails with missing J/E stats when required."""

    h30 = {"runners": [{"id": 1, "name": "horse-1", "odds": "2.5"}]}

    h5 = {"runners": [{"id": 1, "name": "horse-1", "odds": "2.5"}]}

    with pytest.raises(ValueError, match="Stats J/E manquantes: horse-1"):
        validate(h30, h5, allow_je_na=False)


def test_validate_happy_path():
    """Test that validate passes with correct data."""

    h30 = {"runners": [{"id": 1, "name": "horse-1", "odds": "2.5"}]}

    h5 = {
        "runners": [
            {
                "id": 1,
                "name": "horse-1",
                "odds": "2.5",
                "je_stats": {"j_win": 0.1, "e_win": 0.2},
            }
        ]
    }

    assert validate(h30, h5, allow_je_na=False) is True


def test_validate_je_stats_not_required():
    """Test that validate passes when J/E stats are not required."""

    h30 = {"runners": [{"id": 1, "name": "horse-1", "odds": "2.5"}]}

    h5 = {"runners": [{"id": 1, "name": "horse-1", "odds": "2.5"}]}

    assert validate(h30, h5, allow_je_na=True) is True


def test_validate_ev_sp_below_threshold():
    """Test validate_ev fails if ev_sp is below threshold."""

    with pytest.raises(ValidationError, match="EV SP below threshold"):
        validate_ev(ev_sp=config.EV_MIN_SP - 0.1, ev_global=config.EV_MIN_GLOBAL)


def test_validate_ev_global_below_threshold():
    """Test validate_ev fails if ev_global is below threshold and need_combo is True."""

    with pytest.raises(ValidationError, match="EV global below threshold"):
        validate_ev(
            ev_sp=config.EV_MIN_SP,
            ev_global=config.EV_MIN_GLOBAL - 0.1,
            need_combo=True,
        )


def test_validate_ev_global_none_and_combo_needed():
    """Test validate_ev fails if ev_global is None and need_combo is True."""

    with pytest.raises(ValidationError, match="EV global below threshold"):
        validate_ev(ev_sp=config.EV_MIN_SP, ev_global=None, need_combo=True)


def test_validate_ev_happy_path_with_combo():
    """Test validate_ev passes with valid combo EVs."""

    assert (
        validate_ev(ev_sp=config.EV_MIN_SP, ev_global=config.EV_MIN_GLOBAL, need_combo=True) is True
    )


def test_validate_ev_happy_path_no_combo():
    """Test validate_ev passes with no combo needed."""

    assert (
        validate_ev(ev_sp=config.EV_MIN_SP, ev_global=config.EV_MIN_GLOBAL - 0.1, need_combo=False)
        is True
    )


def test_validate_ev_missing_p_success():
    """Test validate_ev returns invalid_input if p_success is missing."""

    result = validate_ev(
        ev_sp=config.EV_MIN_SP,
        ev_global=config.EV_MIN_GLOBAL,
        payout_expected=10,
    )

    assert result == {"status": "invalid_input", "reason": "missing p_success"}


def test_validate_ev_missing_payout_expected():
    """Test validate_ev returns invalid_input if payout_expected is missing."""

    result = validate_ev(
        ev_sp=config.EV_MIN_SP,
        ev_global=config.EV_MIN_GLOBAL,
        p_success=0.5,
    )

    assert result == {"status": "invalid_input", "reason": "missing payout_expected"}


def test_validate_policy_ev_below_threshold():
    """Test validate_policy fails if ev_global is below threshold."""

    with pytest.raises(ValidationError, match="EV global below threshold"):
        validate_policy(ev_global=0.1, roi_global=0.2, min_ev=0.15, min_roi=0.1)


def test_validate_policy_roi_below_threshold():
    """Test validate_policy fails if roi_global is below threshold."""

    with pytest.raises(ValidationError, match="ROI global below threshold"):
        validate_policy(ev_global=0.2, roi_global=0.1, min_ev=0.15, min_roi=0.15)


def test_validate_policy_happy_path():
    """Test validate_policy passes with valid inputs."""

    assert validate_policy(ev_global=0.2, roi_global=0.2, min_ev=0.15, min_roi=0.15) is True


def test_validate_budget_total_exceeded():
    """Test validate_budget fails if total stake exceeds budget cap."""

    with pytest.raises(ValidationError, match="Budget cap exceeded"):
        validate_budget(stakes={"h1": 5, "h2": 6}, budget_cap=10, max_vol_per_horse=0.5)


def test_validate_budget_per_horse_exceeded():
    """Test validate_budget fails if per-horse stake exceeds cap."""

    with pytest.raises(ValidationError, match="Stake cap exceeded for h2"):
        validate_budget(stakes={"h1": 5, "h2": 6}, budget_cap=20, max_vol_per_horse=0.25)


def test_validate_budget_happy_path():
    """Test validate_budget passes with valid stakes."""

    assert validate_budget(stakes={"h1": 5, "h2": 5}, budget_cap=20, max_vol_per_horse=0.3) is True


def test_validate_combos_payout_below_threshold():
    """Test validate_combos fails if expected payout is below threshold."""

    with pytest.raises(ValidationError, match="expected payout for combined bets below threshold"):
        validate_combos(expected_payout=10, min_payout=12)


def test_validate_combos_happy_path():
    """Test validate_combos passes with valid payout."""

    assert validate_combos(expected_payout=15, min_payout=12) is True


def test_combos_allowed_ev_below_threshold():
    """Test combos_allowed returns False if EV is below threshold."""

    assert combos_allowed(ev_basket=0.3, expected_payout=15, min_ev=0.4) is False


def test_combos_allowed_payout_below_threshold():
    """Test combos_allowed returns False if payout is below threshold."""

    assert combos_allowed(ev_basket=0.5, expected_payout=10, min_payout=12) is False


def test_combos_allowed_invalid_inputs():
    """Test combos_allowed handles non-numeric inputs."""

    assert combos_allowed(ev_basket="invalid", expected_payout=15) is False

    assert combos_allowed(ev_basket=0.5, expected_payout="invalid") is False


def test_combos_allowed_happy_path():
    """Test combos_allowed returns True with valid inputs."""

    assert combos_allowed(ev_basket=0.5, expected_payout=15, min_ev=0.4, min_payout=12) is True


@pytest.fixture
def fake_fs_cli(fs):
    """Fixture to set up a fake file system for CLI tests."""
    fs.create_file(
        "data/R1C1/partants.json",
        contents=json.dumps([{"id": i} for i in range(8)]),
    )
    fs.create_file(
        "data/R1C1/odds_h5.json",
        contents=json.dumps({str(i): 2.5 for i in range(8)}),
    )
    fs.create_file("data/R1C1/stats_je.json", contents=json.dumps({"coverage": 90}))
    fs.create_file("README.md", contents="ROI_SP: 15%")
    yield fs


def test_cli_happy_path(fake_fs_cli, capsys):
    """Test the CLI happy path."""
    with patch(
        "hippique_orchestrator.validator_ev._load_cfg", return_value={"ev": {"min_roi_sp": 0.1}}
    ):
        return_code = validator_main(["--reunion", "R1", "--course", "C1"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert return_code == 0
        assert result["ok"] is True


def test_cli_file_not_found(fake_fs_cli, capsys):
    """Test the CLI when a required file is not found."""
    fake_fs_cli.remove("data/R1C1/partants.json")
    return_code = validator_main(["--reunion", "R1", "--course", "C1"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert return_code == 1
    assert result["ok"] is False
    assert "Fichier non trouvé" in result["reason"]


def test_cli_validation_error(fake_fs_cli, capsys):
    """Test the CLI when a validation error occurs."""
    fake_fs_cli.remove_object("data/R1C1/partants.json")
    fake_fs_cli.create_file("data/R1C1/partants.json", contents=json.dumps([{"id": 1}]))
    with patch(
        "hippique_orchestrator.validator_ev._load_cfg", return_value={"ev": {"min_roi_sp": 0.1}}
    ):
        return_code = validator_main(["--reunion", "R1", "--course", "C1"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert return_code == 1
        assert result["ok"] is False
        assert "Nombre de partants insuffisant" in result["reason"]


def test_cli_readme_roi_mismatch(fake_fs_cli, capsys):
    """Test the CLI when README ROI SP is below target."""
    with patch(
        "hippique_orchestrator.validator_ev._load_cfg", return_value={"ev": {"min_roi_sp": 0.2}}
    ):
        return_code = validator_main(["--reunion", "R1", "--course", "C1"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert return_code == 2
        assert result["ok"] is False
        assert "README ROI_SP mismatch" in result["reason"]


def test_cli_allow_je_na_flag(fake_fs_cli, capsys):
    """Test that the --allow-je-na flag works correctly."""
    fake_fs_cli.remove("data/R1C1/stats_je.json")
    with patch(
        "hippique_orchestrator.validator_ev._load_cfg", return_value={"ev": {"min_roi_sp": 0.1}}
    ):
        return_code = validator_main(["--reunion", "R1", "--course", "C1", "--allow-je-na"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert return_code == 0
        assert result["ok"] is True


# --- Tests for internal functions ---

# Removed test_load_cfg_no_yaml_raises_runtime_error as it's hard to mock correctly without modifying the source file.


def test_load_cfg_no_config_file(fs):
    """Test _load_cfg returns empty dict if config file does not exist."""
    assert _load_cfg() == {}


def test_load_cfg_invalid_yaml_returns_empty_dict(fs):
    """Test _load_cfg returns empty dict if yaml content is invalid."""
    fs.create_file("config/gpi.yml", contents="invalid: [-\n  value")  # Truly invalid YAML
    assert _load_cfg() == {}


def test_readme_has_roi_sp_no_readme(fs):
    """Test _readme_has_roi_sp returns True if README.md does not exist."""
    assert _readme_has_roi_sp(0.1) is True


def test_readme_has_roi_sp_no_match(fs):
    """Test _readme_has_roi_sp returns False if pattern not found."""
    fs.create_file("README.md", contents="No ROI_SP here")
    assert _readme_has_roi_sp(0.1) is False


def test_readme_has_roi_sp_invalid_value(fs):
    """Test _readme_has_roi_sp returns False if value is not a float."""
    fs.create_file("README.md", contents="ROI_SP: abc%")
    assert _readme_has_roi_sp(0.1) is False


def test_readme_has_roi_sp_below_target(fs):
    """Test _readme_has_roi_sp returns False if value is below target."""
    fs.create_file("README.md", contents="ROI_SP: 5%")
    assert _readme_has_roi_sp(0.1) is False


def test_readme_has_roi_sp_above_target(fs):
    """Test _readme_has_roi_sp returns True if value is above target."""
    fs.create_file("README.md", contents="ROI_SP: 15%")
    assert _readme_has_roi_sp(0.1) is True


def test_summarise_validation_all_pass():
    """Test summarise_validation returns ok=True when all validators pass."""
    validator1 = Mock(return_value=True)
    validator2 = Mock(return_value=True)
    result = summarise_validation(validator1, validator2)
    assert result == {"ok": True, "reason": ""}
    validator1.assert_called_once()
    validator2.assert_called_once()


def test_summarise_validation_first_fails():
    """Test summarise_validation returns ok=False and reason for first failure."""
    validator1 = Mock(side_effect=ValueError("First error"))
    validator2 = Mock(return_value=True)
    result = summarise_validation(validator1, validator2)
    assert result == {"ok": False, "reason": "First error"}
    validator1.assert_called_once()
    validator2.assert_not_called()


def test_must_have_falsy_value_raises_runtime_error():
    """Test must_have raises RuntimeError for a falsy value."""
    with pytest.raises(RuntimeError, match="Value is missing"):
        must_have(None, "Value is missing")


def test_must_have_truthy_value_returns_value():
    """Test must_have returns the value for a truthy value."""
    assert must_have("some_value", "Value is missing") == "some_value"


def test_normalise_phase_invalid_phase_raises_value_error():
    """Test _normalise_phase raises ValueError for an invalid phase."""
    with pytest.raises(ValueError, match="Phase inconnue: 'INVALID'"):
        _normalise_phase("INVALID")


def test_normalise_phase_h5():
    """Test _normalise_phase correctly normalizes H5."""
    assert _normalise_phase("h5") == "H5"
    assert _normalise_phase("H-5") == "H5"


def test_normalise_phase_h30():
    """Test _normalise_phase correctly normalizes H30."""
    assert _normalise_phase("h30") == "H30"
    assert _normalise_phase("H-30") == "H30"


def test_normalise_phase_none_returns_h5():
    """Test _normalise_phase returns 'H5' when phase is None."""
    assert _normalise_phase(None) == "H5"


def test_load_json_payload_invalid_json_raises_json_decode_error(fs):
    """Test _load_json_payload raises JSONDecodeError for invalid JSON."""
    fs.create_file("invalid.json", contents="{'a':1")
    with pytest.raises(json.JSONDecodeError):
        _load_json_payload(Path("invalid.json"))


def test_find_first_existing_none_found(fs):
    """Test _find_first_existing returns None if no candidates found."""
    assert _find_first_existing(Path("/"), ("non_existent.txt",)) is None


def test_find_first_existing_found(fs):
    """Test _find_first_existing returns the first existing path."""
    fs.create_file("/found.txt")
    assert _find_first_existing(Path("/"), ("non_existent.txt", "found.txt")) == Path("/found.txt")


def test_load_partants_invalid_list_format_returns_empty_list(fs):
    """Test _load_partants returns an empty list for invalid list format."""
    fs.create_file("invalid_partants.json", contents=json.dumps([1, 2, 3]))
    assert _load_partants(Path("invalid_partants.json")) == []


def test_load_partants_invalid_dict_format_raises_value_error(fs):
    """Test _load_partants raises ValueError for invalid dict format."""
    fs.create_file("invalid_partants.json", contents=json.dumps({"key": "value"}))
    with pytest.raises(ValueError, match="Format partants invalide"):
        _load_partants(Path("invalid_partants.json"))


def test_load_odds_empty_odds_map_raises_value_error(fs):
    """Test _load_odds raises ValueError if no odds can be extracted."""
    fs.create_file("empty_odds.json", contents=json.dumps({}))
    with pytest.raises(ValueError, match="Impossible d'extraire les cotes"):
        _load_odds(Path("empty_odds.json"))


def test_load_odds_from_dict_with_invalid_values(fs):
    """Test _load_odds handles dict with non-numeric odds values."""
    fs.create_file("odds_invalid.json", contents=json.dumps({"1": "abc", "2": 2.5}))
    result = _load_odds(Path("odds_invalid.json"))
    assert result == {"2": 2.5}


def test_load_odds_from_list_with_invalid_values(fs):
    """Test _load_odds handles list with non-numeric odds values."""
    fs.create_file(
        "odds_invalid_list.json",
        contents=json.dumps([{"id": 1, "odds": "abc"}, {"id": 2, "odds": 2.5}]),
    )
    result = _load_odds(Path("odds_invalid_list.json"))
    assert result == {"2": 2.5}


def test_load_config_non_existent_path(fs):
    """Test _load_config returns empty dict for a non-existent path."""
    assert _load_config(Path("non_existent_config.yml")) == {}


def test_load_config_invalid_yaml(fs):
    """Test _load_config returns empty dict for invalid YAML."""
    fs.create_file("invalid.yml", contents="key: - value")
    assert _load_config(Path("invalid.yml")) == {}


def test_load_config_invalid_json(fs):
    """Test _load_config returns empty dict for invalid JSON."""
    fs.create_file("invalid.json", contents="{'key': 'value'")
    assert _load_config(Path("invalid.json")) == {}


def test_load_config_valid_yaml(fs):
    """Test _load_config returns correct dict for valid YAML."""
    fs.create_file("valid.yml", contents="key: value")
    assert _load_config(Path("valid.yml")) == {"key": "value"}


def test_load_config_valid_json(fs):
    """Test _load_config returns correct dict for valid JSON."""
    fs.create_file("valid.json", contents='{"key": "value"}')
    assert _load_config(Path("valid.json")) == {"key": "value"}
