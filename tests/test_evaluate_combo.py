import os
from pathlib import Path

from simulate_wrapper import evaluate_combo


TICKETS = [{"legs": ["a", "b"], "odds": 10.0, "stake": 1.0}]


def test_gates_when_calibration_missing(tmp_path, monkeypatch):
    calib = tmp_path / "payout_calibration.yaml"
    if calib.exists():
        calib.unlink()
    monkeypatch.delenv("ALLOW_HEURISTIC", raising=False)
    res = evaluate_combo(TICKETS, bankroll=10.0, calibration=calib)
    assert res["status"] == "insufficient_data"
    assert res["ev_ratio"] == 0.0
    assert res["payout_expected"] == 0.0
    assert "no_calibration_yaml" in res["notes"]
    assert str(calib) in res["requirements"]


def test_override_missing_calibration(tmp_path, monkeypatch):
    calib = tmp_path / "payout_calibration.yaml"
    if calib.exists():
        calib.unlink()
    monkeypatch.setenv("ALLOW_HEURISTIC", "1")
    res = evaluate_combo(TICKETS, bankroll=10.0, calibration=calib)
    assert res["status"] == "ok"
    assert res["ev_ratio"] > 0.0
    assert res["payout_expected"] > 0.0
    assert "no_calibration_yaml" in res["notes"]


def test_with_calibration(tmp_path, monkeypatch):
    calib = tmp_path / "payout_calibration.yaml"
    calib.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("ALLOW_HEURISTIC", raising=False)
    res = evaluate_combo(TICKETS, bankroll=10.0, calibration=calib)
    assert res["status"] == "ok"
    assert res["ev_ratio"] > 0.0
    assert res["payout_expected"] > 0.0
    assert res["notes"] == []
    assert res["requirements"] == []
