from collections import OrderedDict
from pathlib import Path

from hippique_orchestrator import simulate_wrapper as sw
from hippique_orchestrator.simulate_wrapper import evaluate_combo

TICKETS = [{"legs": ["a", "b"], "odds": 10.0, "stake": 1.0}]


def test_default_config_path_missing(monkeypatch, tmp_path):
    """When env var unset we fall back to bundled calibration hints."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CALIB_PATH", raising=False)
    res = evaluate_combo(TICKETS, bankroll=10.0)
    assert res["status"] == "insufficient_data"
    assert res["calibration_used"] is False
    assert "Calibration" in res["message"]
    assert str(sw.PAYOUT_CALIBRATION_PATH) in res["requirements"]
    assert str(Path("config/payout_calibration.yaml")) in res["requirements"]


def test_env_path_missing(monkeypatch, tmp_path):
    """Env var pointing to missing file should gate evaluation."""
    calib = tmp_path / "custom_payout.yaml"
    if calib.exists():
        calib.unlink()
    monkeypatch.delenv("ALLOW_HEURISTIC", raising=False)
    monkeypatch.setenv("CALIB_PATH", str(calib))
    res = evaluate_combo(TICKETS, bankroll=10.0)
    assert res["status"] == "insufficient_data"
    assert "test/calib/path" in res["requirements"]


def test_env_path_present(monkeypatch, tmp_path, mock_config):
    """Env var should be honoured when file exists."""
    calib = tmp_path / "custom_payout.yaml"
    calib.write_text("correlations: {}", encoding="utf-8")
    monkeypatch.setattr(
        mock_config, "CALIB_PATH", str(calib)
    )  # Set CALIB_PATH on the mocked config

    prob_calib = tmp_path / "probabilities.yaml"
    prob_calib.write_text(
        """
a|b:
  p: 0.2
"""
    )
    monkeypatch.setattr(sw, "CALIBRATION_PATH", prob_calib)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)

    res = evaluate_combo(TICKETS, bankroll=10.0)
    assert res["status"] == "ok"
    assert res["notes"] == []
    assert res["requirements"] == []
    assert res["calibration_used"] is True


def test_gates_when_calibration_missing(tmp_path, monkeypatch):
    calib = tmp_path / "payout_calibration.yaml"
    if calib.exists():
        calib.unlink()
    monkeypatch.delenv("CALIB_PATH", raising=False)
    res = evaluate_combo(TICKETS, bankroll=10.0, calibration=calib)
    assert res["status"] == "insufficient_data"
    assert res["calibration_used"] is False
    assert "ev_ratio" not in res
    assert "roi" not in res
    assert "payout_expected" not in res
    assert "no_calibration_yaml" in res["notes"]
    assert str(calib) in res["requirements"]


def test_override_missing_calibration(tmp_path, monkeypatch):
    calib = tmp_path / "payout_calibration.yaml"
    if calib.exists():
        calib.unlink()
    monkeypatch.delenv("CALIB_PATH", raising=False)
    res = evaluate_combo(
        TICKETS,
        bankroll=10.0,
        calibration=calib,
        allow_heuristic=True,
    )
    assert res["status"] == "insufficient_data"
    assert res["calibration_used"] is False
    assert "no_calibration_yaml" in res["notes"]
    assert "skeleton" in res["message"]


def test_with_calibration(tmp_path, monkeypatch):
    calib = tmp_path / "payout_calibration.yaml"
    calib.write_text("correlations: {}", encoding="utf-8")
    monkeypatch.delenv("CALIB_PATH", raising=False)

    prob_calib = tmp_path / "probabilities.yaml"
    prob_calib.write_text(
        """
a|b:
  p: 0.2
"""
    )
    monkeypatch.setattr(sw, "CALIBRATION_PATH", prob_calib)
    monkeypatch.setattr(sw, "_calibration_cache", OrderedDict())
    monkeypatch.setattr(sw, "_calibration_mtime", 0.0)

    res = evaluate_combo(TICKETS, bankroll=10.0, calibration=calib)
    assert res["status"] == "ok"
    assert res["ev_ratio"] > 0.0
    assert res["roi"] > 0.0
    assert res["payout_expected"] > 0.0
    assert res["calibration_used"] is True
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
    calib_path.write_text("{}", encoding="utf-8")

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
    assert res["calibration_used"] is True
