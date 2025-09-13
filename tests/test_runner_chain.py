import runner_chain


def test_validate_exotics_with_simwrapper_filters_and_alert(monkeypatch):
    def fake_eval(tickets, bankroll, allow_heuristic=True):
        if tickets[0]['id'] == 'fail':
            return {'ev_ratio': 0.1, 'payout_expected': 5.0, 'notes': [], 'requirements': []}
        return {'ev_ratio': 0.6, 'payout_expected': 25.0, 'notes': [], 'requirements': []}

    monkeypatch.setattr(runner_chain, 'evaluate_combo', fake_eval)

    exotics = [
        [{'id': 'fail', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}],
        [{'id': 'ok', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}],
    ]

    tickets, info = runner_chain.validate_exotics_with_simwrapper(exotics, bankroll=5)
    assert len(tickets) == 1
    assert tickets[0]['flags'] == ['ALERTE_VALUE']
    assert info['flags']['combo'] is True


def test_export_tracking_csv_line(tmp_path):
    path = tmp_path / 'track.csv'
    meta = {'reunion': 'R1', 'course': 'C1', 'hippodrome': 'X', 'date': '2024-01-01', 'discipline': 'plat', 'partants': 8}
    tickets = [{'stake': 2.0}, {'stake': 1.0}]
    stats = {'ev_sp': 0.3, 'ev_global': 0.6, 'roi_sp': 0.2, 'roi_global': 0.5, 'risk_of_ruin': 0.1, 'clv_moyen': 0.0, 'model': 'M'}

    runner_chain.export_tracking_csv_line(str(path), meta, tickets, stats, alerte=True)

    lines = path.read_text(encoding='utf-8').splitlines()
    assert lines[0].split(';')[-1] == 'ALERTE_VALUE'
    assert lines[1].split(';')[-1] == 'ALERTE_VALUE'
