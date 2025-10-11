import runner_chain


def test_validate_exotics_requires_calibration(tmp_path, monkeypatch):
    def fake_evaluate(tickets, bankroll, calibration=None, allow_heuristic=False):
        raise AssertionError("evaluation should be skipped when calibration missing")

    monkeypatch.setattr(runner_chain, "evaluate_combo", fake_evaluate)

    combos = [
        [{"id": "CP1", "legs": ["1", "2"], "stake": 1.0, "p": 0.05, "odds": 12.0}]
    ]

    calibration_path = tmp_path / "missing_calibration.yaml"

    tickets, info = runner_chain.validate_exotics_with_simwrapper(
        combos,
        bankroll=50.0,
        calibration=str(calibration_path),
    )

    assert tickets == []
    assert info["status"] == "insufficient_data"
    assert info["decision"] == "reject:calibration_missing"
    assert info["flags"]["combo"] is False
    assert info["flags"]["reasons"]["combo"] == ["calibration_missing"]
    assert info["notes"] == [
        "calibration_missing",
        "no_calibration_yaml → exotiques désactivés",
    ]
