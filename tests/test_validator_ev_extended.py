
import pytest
from hippique_orchestrator import validator_ev
from hippique_orchestrator.validator_ev import ValidationError


def test_validate_inputs_success():
    cfg = {"ALLOW_JE_NA": True}
    partants = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}, {"id": 6}]
    odds = {"1": 2.0, "2": 3.0, "3": 4.0, "4": 5.0, "5": 6.0, "6": 7.0}
    stats_je = {"coverage": 90.0}
    assert validator_ev.validate_inputs(cfg, partants, odds, stats_je) is True


def test_validate_inputs_not_enough_partants():
    cfg = {"ALLOW_JE_NA": True}
    partants = [{"id": 1}]
    odds = {"1": 2.0}
    stats_je = {"coverage": 90.0}
    with pytest.raises(ValidationError, match="Nombre de partants insuffisant"):
        validator_ev.validate_inputs(cfg, partants, odds, stats_je)


def test_validate_inputs_missing_odds():
    cfg = {"ALLOW_JE_NA": True}
    partants = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}, {"id": 6}]
    odds = {}
    stats_je = {"coverage": 90.0}
    with pytest.raises(ValidationError, match="Cotes manquantes"):
        validator_ev.validate_inputs(cfg, partants, odds, stats_je)


def test_validate_inputs_missing_je_coverage():
    cfg = {"ALLOW_JE_NA": False}
    partants = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}, {"id": 6}]
    odds = {"1": 2.0, "2": 3.0, "3": 4.0, "4": 5.0, "5": 6.0, "6": 7.0}
    stats_je = {"coverage": 70.0}
    with pytest.raises(ValidationError, match="Couverture J/E insuffisante"):
        validator_ev.validate_inputs(cfg, partants, odds, stats_je)


def test_validate_success():
    h30 = {
        "runners": [
            {"id": "1", "odds": "2.0"},
            {"id": "2", "odds": "3.0"},
        ]
    }
    h5 = {
        "runners": [
            {"id": "1", "odds": "2.1"},
            {"id": "2", "odds": "3.1"},
        ]
    }
    assert validator_ev.validate(h30, h5, allow_je_na=True) is True


def test_validate_inconsistent_partants():
    h30 = {"runners": [{"id": "1", "odds": "2.0"}]}
    h5 = {"runners": [{"id": "2", "odds": "3.0"}]}
    with pytest.raises(ValueError, match="Partants incohérents"):
        validator_ev.validate(h30, h5, allow_je_na=True)


def test_validate_no_partants():
    h30 = {"runners": []}
    h5 = {"runners": []}
    with pytest.raises(ValueError, match="Aucun partant"):
        validator_ev.validate(h30, h5, allow_je_na=True)


def test_validate_missing_h30_odds():
    h30 = {"runners": [{"id": "1"}]}
    h5 = {"runners": [{"id": "1", "odds": "2.0"}]}
    with pytest.raises(ValueError, match="Cotes manquantes H-30"):
        validator_ev.validate(h30, h5, allow_je_na=True)


def test_validate_invalid_odds():
    h30 = {"runners": [{"id": "1", "odds": "1.0"}]}
    h5 = {"runners": [{"id": "1", "odds": "2.0"}]}
    with pytest.raises(ValueError, match="Cote non numérique H-30 pour 1: 1.0"):
        validator_ev.validate(h30, h5, allow_je_na=True)


def test_validate_missing_je_stats():
    h30 = {"runners": [{"id": "1", "odds": "2.0"}]}
    h5 = {"runners": [{"id": "1", "odds": "2.0"}]}
    with pytest.raises(ValueError, match="Stats J/E manquantes"):
        validator_ev.validate(h30, h5, allow_je_na=False)


def test_validate_policy_success():
    assert validator_ev.validate_policy(0.5, 0.3, 0.4, 0.2) is True


def test_validate_policy_ev_fail():
    with pytest.raises(ValidationError, match="EV global below threshold"):
        validator_ev.validate_policy(0.3, 0.3, 0.4, 0.2)


def test_validate_policy_roi_fail():
    with pytest.raises(ValidationError, match="ROI global below threshold"):
        validator_ev.validate_policy(0.5, 0.1, 0.4, 0.2)


def test_validate_budget_success():
    stakes = {"1": 10, "2": 20}
    assert validator_ev.validate_budget(stakes, 100, 0.5) is True


def test_validate_budget_cap_exceeded():
    stakes = {"1": 60, "2": 50}
    with pytest.raises(ValidationError, match="Budget cap exceeded"):
        validator_ev.validate_budget(stakes, 100, 0.5)


def test_validate_budget_per_horse_cap_exceeded():
    stakes = {"1": 60, "2": 20}
    with pytest.raises(ValidationError, match="Stake cap exceeded for 1"):
        validator_ev.validate_budget(stakes, 100, 0.5)


def test_validate_combos_success():
    assert validator_ev.validate_combos(15.0, 12.0) is True


def test_validate_combos_fail():
    with pytest.raises(ValidationError, match="expected payout for combined bets below threshold"):
        validator_ev.validate_combos(10.0, 12.0)


def test_combos_allowed_success():
    assert validator_ev.combos_allowed(0.5, 15.0) is True


def test_combos_allowed_ev_fail():
    assert validator_ev.combos_allowed(0.3, 15.0) is False


def test_combos_allowed_payout_fail():
    assert validator_ev.combos_allowed(0.5, 10.0) is False


def test_cli_success(mocker):
    """Test the CLI with successful validation."""
    mocker.patch(
        "hippique_orchestrator.validator_ev._prepare_validation_inputs",
        return_value=({}, [], {}, {}),
    )
    mocker.patch(
        "hippique_orchestrator.validator_ev.summarise_validation",
        return_value={"ok": True, "reason": ""},
    )
    mocker.patch(
        "hippique_orchestrator.validator_ev._readme_has_roi_sp",
        return_value=True,
    )
    mocker.patch(
        "hippique_orchestrator.validator_ev._load_cfg",
        return_value={},
    )
    
    # Mock sys.argv
    argv = [
        "--reunion", "R1",
        "--course", "C1",
    ]
    
    return_code = validator_ev._cli(argv)
    assert return_code == 0
    

def test_cli_fail(mocker):
    """Test the CLI with failed validation."""
    mocker.patch(
        "hippique_orchestrator.validator_ev._prepare_validation_inputs",
        return_value=({}, [], {}, {}),
    )
    mocker.patch(
        "hippique_orchestrator.validator_ev.summarise_validation",
        return_value={"ok": False, "reason": "Test failure"},
    )
    mocker.patch(
        "hippique_orchestrator.validator_ev._readme_has_roi_sp",
        return_value=True,
    )
    mocker.patch(
        "hippique_orchestrator.validator_ev._load_cfg",
        return_value={},
    )
    
    # Mock sys.argv
    argv = [
        "--reunion", "R1",
        "--course", "C1",
    ]
    
    return_code = validator_ev._cli(argv)
    assert return_code == 1

