from tickets_builder import _validate_exotics_with_simwrapper


def test_combo_rejected_by_ev(monkeypatch):
    def fake_eval(tickets, bankroll, calibration=None, allow_heuristic=False):
        return {
            "status": "ok",
            "ev_ratio": 0.35,
            "roi": 0.5,
            "payout_expected": 50.0,
            "sharpe": 0.4,
            "notes": [],
            "requirements": [],
        }

    monkeypatch.setattr("tickets_builder.evaluate_combo", fake_eval)

    tickets, info = _validate_exotics_with_simwrapper(
        [[{"id": "low_ev", "p": 0.5, "odds": 2.0, "stake": 1.0}]],
        bankroll=10,
        ev_min=0.4,
        roi_min=0.0,
        payout_min=0.0,
        sharpe_min=0.0,
        allow_heuristic=False,
        calibration=None,
    )

    assert tickets == []
    assert "ev_below_threshold" in info["flags"]["reasons"]["combo"]
