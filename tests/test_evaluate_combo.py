from collections import OrderedDict
from pathlib import Path

import simulate_wrapper as sw

from simulate_wrapper import evaluate_combo


TICKETS = [{"legs": ["a", "b"], "odds": 10.0, "stake": 1.0}]


def test_default_config_path_missing(monkeypatch, tmp_path):
    """When env var unset we fall back to config/ path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CALIB_PATH", raising=False)
    monkeypatch.delenv("ALLOW_HEURISTIC", raising=False)
    res = evaluate_combo(TICKETS, bankroll=10.0)
    assert res["status"] == "insufficient_data"
    assert str(Path("config/payout_calibration.yaml")) in res["requirements"]


def test_env_path_missing(monkeypatch, tmp_path):
    """Env var pointing to missing file should gate evaluation."""
    calib = tmp_path / "custom_payout.yaml"
    if calib.exists():
        calib.unlink()
    monkeypatch.setenv("CALIB_PATH", str(calib))
    monkeypatch.delenv("ALLOW_HEURISTIC", raising=False)
    res = evaluate_combo(TICKETS, bankroll=10.0)
    assert res["status"] == "insufficient_data"
    assert str(calib) in res["requirements"]


def test_env_path_present(monkeypatch, tmp_path):
    """Env var should be honoured when file exists."""
    calib = tmp_path / "custom_payout.yaml"
    calib.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CALIB_PATH", str(calib))
    monkeypatch.delenv("ALLOW_HEURISTIC", raising=False)
    res = evaluate_combo(TICKETS, bankroll=10.0)
    assert res["status"] == "ok"
    assert res["notes"] == []
    assert res["requirements"] == []
    assert str(Path("payout_calibration.yaml")) in res["requirements"]


def test_gates_when_calibration_missing(tmp_path, monkeypatch):
    calib = tmp_path / "payout_calibration.yaml"
    if calib.exists():
        calib.unlink()
    monkeypatch.delenv("CALIB_PATH", raising=False)
    monkeypatch.delenv("ALLOW_HEURISTIC", raising=False)
    res = evaluate_combo(TICKETS, bankroll=10.0, calibration=calib)
    assert res["status"] == "insufficient_data"
    assert res["ev_ratio"] == 0.0
    assert res["roi"] == 0.0
    assert res["payout_expected"] == 0.0
    assert "no_calibration_yaml" in res["notes"]
    assert str(calib) in res["requirements"]


def test_override_missing_calibration(tmp_path, monkeypatch):
    calib = tmp_path / "payout_calibration.yaml"
    if calib.exists():
        calib.unlink()
    monkeypatch.delenv("CALIB_PATH", raising=False)
    monkeypatch.setenv("ALLOW_HEURISTIC", "1")
    res = evaluate_combo(TICKETS, bankroll=10.0, calibration=calib)
    assert res["status"] == "ok"
    assert res["ev_ratio"] > 0.0
    assert res["roi"] > 0.0
    assert res["payout_expected"] > 0.0
    assert "no_calibration_yaml" in res["notes"]


def test_with_calibration(tmp_path, monkeypatch):
    calib = tmp_path / "payout_calibration.yaml"
    calib.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("CALIB_PATH", raising=False)
    monkeypatch.delenv("ALLOW_HEURISTIC", raising=False)
    res = evaluate_combo(TICKETS, bankroll=10.0, calibration=calib)
    assert res["status"] == "ok"
    assert res["ev_ratio"] > 0.0
    assert res["roi"] > 0.0
    assert res["payout_expected"] > 0.0
    assert res["notes"] == []
    assert res["requirements"] == []


def test_marks_unreliable_probabilities(monkeypatch, tmp_path):
    """When only implied odds are available the combo is flagged."""
    cal = tmp_path / "probabilities.yaml"
    cal.write_text("")
    monkeypatch.setattr(sw, "CALIBRATION_PATH", cal)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)

    tickets = [
        {
            "legs": [
                {"id": "L1", "odds": 5.0},
                {"id": "L2", "odds": 4.0},
            ],
            "odds": 10.0,
            "stake": 1.0,
        }
    ]

    calib_path = tmp_path / "payout_calibration.yaml"
    if calib_path.exists():
        calib_path.unlink()
    monkeypatch.delenv("CALIB_PATH", raising=False)

    res = evaluate_combo(
        tickets,
        bankroll=10.0,
        calibration=calib_path,
        allow_heuristic=True,
    )

    assert res["status"] == "ok"
    assert "combo_probabilities_unreliable" in res["notes"]
    assert res["ev_ratio"] <= 0.0
    assert res["roi"] <= 0.0
