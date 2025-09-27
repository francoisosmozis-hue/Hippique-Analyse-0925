import runner_chain


def test_combo_rejected_by_ev(monkeypatch):
    def fake_eval(tickets, bankroll, allow_heuristic=False):
        return {
            'status': 'ok',
            'ev_ratio': 0.35,
            'roi': 0.5,
            'payout_expected': 50.0,
            'sharpe': 0.4,
            'notes': [],
            'requirements': [],
        }

    monkeypatch.setattr(runner_chain, 'evaluate_combo', fake_eval)

    tickets, info = runner_chain.validate_exotics_with_simwrapper(
        [[{'id': 'low_ev', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}]],
        bankroll=10,
    )

    assert tickets == []
    assert info['decision'] == 'reject:ev_ratio_below_accept_threshold'
    assert info['flags']['reasons']['combo'] == ['ev_ratio_below_accept_threshold']
