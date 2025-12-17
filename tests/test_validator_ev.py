import json
import os
import subprocess
import sys
from functools import partial

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from hippique_orchestrator.validator_ev import (
    ValidationError,
    combos_allowed,
    summarise_validation,
    validate_combos,
    validate_ev,
    validate_inputs,
    validate_policy,
)


def test_validate_ev_passes_with_defaults(monkeypatch):
    monkeypatch.delenv("EV_MIN_SP", raising=False)
    monkeypatch.delenv("EV_MIN_GLOBAL", raising=False)
    assert validate_ev(ev_sp=0.5, ev_global=0.5)

def test_validate_ev_sp_below_threshold(monkeypatch):
    monkeypatch.setenv("EV_MIN_SP", "0.2")
    with pytest.raises(ValidationError):
        validate_ev(ev_sp=0.1, ev_global=1.0)

def test_validate_ev_combo_optional(monkeypatch):
    monkeypatch.setenv("EV_MIN_SP", "0.2")
    assert validate_ev(ev_sp=0.3, ev_global=None, need_combo=False)

def test_validate_ev_combo_required(monkeypatch):
    monkeypatch.setenv("EV_MIN_SP", "0.2")
    monkeypatch.setenv("EV_MIN_GLOBAL", "0.4")
    with pytest.raises(ValidationError):
        validate_ev(ev_sp=0.5, ev_global=0.2, need_combo=True)


def test_validate_ev_logs_context(monkeypatch, caplog):
    monkeypatch.delenv("EV_MIN_SP", raising=False)
    monkeypatch.delenv("EV_MIN_GLOBAL", raising=False)
    caplog.set_level("INFO", logger="validator_ev")

    result = validate_ev(
        ev_sp=0.5,
        ev_global=0.6,
        p_success=0.45,
        payout_expected=18.0,
        stake=10.0,
        ev_ratio=0.35,
    )

    assert result is True
    logged = [
        record.message
        for record in caplog.records
        if "[validate_ev] context" in record.message
    ]
    assert logged, "validate_ev should log contextual metrics"
    log_line = logged[-1]
    assert "'p_success': 0.45" in log_line
    assert "'payout_expected': 18.0" in log_line
    assert "'stake': 10.0" in log_line
    assert "'EV_ratio': 0.35" in log_line


def test_validate_ev_invalid_input_for_missing_probability():
    result = validate_ev(
        ev_sp=0.5,
        ev_global=0.6,
        p_success=None,
        payout_expected=25.0,
    )

    assert result == {"status": "invalid_input", "reason": "missing p_success"}


def test_validate_ev_invalid_input_for_missing_payout():
    result = validate_ev(
        ev_sp=0.5,
        ev_global=0.6,
        p_success=0.45,
        payout_expected=None,
    )

    assert result == {"status": "invalid_input", "reason": "missing payout_expected"}


def test_validate_policy_pass():
    assert validate_policy(ev_global=0.5, roi_global=0.3, min_ev=0.4, min_roi=0.2)


def test_validate_policy_fail_ev():
    with pytest.raises(ValidationError):
        validate_policy(ev_global=0.3, roi_global=0.3, min_ev=0.4, min_roi=0.2)


def test_validate_policy_fail_roi():
    with pytest.raises(ValidationError):
        validate_policy(ev_global=0.5, roi_global=0.1, min_ev=0.4, min_roi=0.2)


def test_validate_combos_pass():
    # Defaults to a minimum payout of 12.0
    assert validate_combos(expected_payout=13.0)


def test_validate_combos_fail_default():
    # When no minimum payout is provided the default (12.0) is applied
    with pytest.raises(ValidationError):
        validate_combos(expected_payout=11.0)


def test_combos_allowed_thresholds():
    assert combos_allowed(0.45, 15.0)
    assert not combos_allowed(0.30, 20.0)
    assert not combos_allowed(0.45, 10.0)


def _sample_partants(n=6):
    return [{"id": str(i)} for i in range(1, n + 1)]


def _sample_odds(n=6):
    return {str(i): float(i + 1) for i in range(1, n + 1)}


def test_validate_inputs_ok():
    cfg = {}
    partants = _sample_partants()
    odds = _sample_odds()
    stats = {"coverage": 80}
    assert validate_inputs(cfg, partants, odds, stats)


def test_validate_inputs_partants_insuffisants():
    partants = _sample_partants(5)
    odds = _sample_odds(5)
    stats = {"coverage": 80}
    with pytest.raises(ValidationError):
        validate_inputs({}, partants, odds, stats)


def test_validate_inputs_cote_none():
    partants = _sample_partants()
    odds = _sample_odds()
    odds["3"] = None
    stats = {"coverage": 80}
    with pytest.raises(ValidationError):
        validate_inputs({}, partants, odds, stats)


def test_validate_inputs_couverture():
    partants = _sample_partants()
    odds = _sample_odds()
    stats = {"coverage": 70}
    with pytest.raises(ValidationError):
        validate_inputs({}, partants, odds, stats)

    cfg = {"ALLOW_JE_NA": True}
    assert validate_inputs(cfg, partants, odds, stats)


def test_summarise_validation_success():
    cfg = {}
    partants = _sample_partants()
    odds = _sample_odds()
    stats = {"coverage": 90}
    summary = summarise_validation(
        partial(validate_inputs, cfg, partants, odds, stats)
    )
    assert summary == {"ok": True, "reason": ""}


def test_summarise_validation_failure_returns_reason():
    cfg = {}
    partants = _sample_partants(5)
    odds = _sample_odds(5)
    stats = {"coverage": 85}
    summary = summarise_validation(
        partial(validate_inputs, cfg, partants, odds, stats)
    )
    assert summary["ok"] is False
    assert "partants" in summary["reason"].lower()
    with pytest.raises(ValidationError):
        validate_inputs(cfg, partants, odds, stats)


def test_validator_cli_returns_non_zero_on_failure(tmp_path):
    artefacts_dir = tmp_path

    partants = {"runners": _sample_partants(5)}
    odds = {str(i): float(i + 1) for i in range(1, 6)}
    stats = {"coverage": 90}

    (artefacts_dir / "partants.json").write_text(json.dumps(partants), encoding="utf-8")
    (artefacts_dir / "h5.json").write_text(json.dumps(odds), encoding="utf-8")
    (artefacts_dir / "stats_je.json").write_text(json.dumps(stats), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "hippique_orchestrator.validator_ev", "--artefacts", str(artefacts_dir)],
        check=False, capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    summary = json.loads(result.stdout.strip())
    assert summary.get("ok") is False
    assert "partants" in summary.get("reason", "").lower()
