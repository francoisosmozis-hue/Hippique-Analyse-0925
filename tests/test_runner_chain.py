import pytest

import runner_chain


def test_compute_overround_cap_flat_handicap_string_partants() -> None:
    cap = runner_chain.compute_overround_cap("Handicap de Plat", "16 partants")
    assert cap == pytest.approx(1.25)


def test_compute_overround_cap_context_reports_reason() -> None:
    context: dict[str, object] = {}
    cap = runner_chain.compute_overround_cap(
        "Handicap de Plat",
        16,
        context=context,
        course_label="Grand Handicap de Paris",
    )
    assert cap == pytest.approx(1.25)
    assert context.get("triggered") is True
    assert context.get("reason") == "flat_handicap"
    assert context.get("default_cap") == pytest.approx(1.30)
    assert context.get("partants") == 16
    assert context.get("discipline") == "handicap de plat"


def test_compute_overround_cap_other_disciplines() -> None:
    cap = runner_chain.compute_overround_cap("Trot Attelé", 12)
    assert cap == pytest.approx(1.30)


def test_compute_overround_cap_detects_handicap_from_course_label() -> None:
    cap = runner_chain.compute_overround_cap(
        None,
        "15 partants",
        course_label="Grand Handicap de Paris",
    )
    assert cap == pytest.approx(1.25)


def test_compute_overround_cap_handles_accents() -> None:
    cap = runner_chain.compute_overround_cap("Handicap de Plât", "14 partants")
    assert cap == pytest.approx(1.25) 


def test_validate_exotics_with_simwrapper_filters_and_alert(monkeypatch):
    def fake_eval(tickets, bankroll, allow_heuristic=True):
        if tickets[0]['id'] == 'fail':
            return {
                'ev_ratio': 0.1,
                'roi': 0.05,
                'payout_expected': 5.0,
                'sharpe': 0.2,
                'notes': [],
                'requirements': []
            }
        return {
            'ev_ratio': 0.6,
            'roi': 0.8,
            'payout_expected': 25.0,
            'sharpe': 0.2,
            'notes': [],
            'requirements': []
        }

    monkeypatch.setattr(runner_chain, 'evaluate_combo', fake_eval)

    exotics = [
        [{'id': 'fail', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}],
        [{'id': 'ok', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}],
    ]

    tickets, info = runner_chain.validate_exotics_with_simwrapper(exotics, bankroll=5)
    assert len(tickets) == 1
    assert tickets[0]['flags'] == ['ALERTE_VALUE']
    assert info['flags']['combo'] is True
    assert info['decision'] == 'accept'


def test_validate_exotics_with_simwrapper_rejects_low_payout(monkeypatch):
    def fake_eval(tickets, bankroll, allow_heuristic=True):
        return {
            'ev_ratio': 0.8,
            'roi': 0.7,
            'payout_expected': 5.0,
            'sharpe': 0.7,
            'notes': [],
            'requirements': []
        }

    monkeypatch.setattr(runner_chain, 'evaluate_combo', fake_eval)

    tickets, info = runner_chain.validate_exotics_with_simwrapper(
        [[{'id': 'low', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}]],
        bankroll=10,
        payout_min=10.0,
    )

    assert tickets == []
    assert 'payout_expected_below_accept_threshold' in info['flags']['reasons']['combo']
    assert info['flags']['combo'] is False
    assert info['decision'] == 'reject:payout_expected_below_accept_threshold'


def test_validate_exotics_with_simwrapper_caps_best_and_alert(monkeypatch):
    results = {
        'a': {'ev_ratio': 0.6, 'roi': 0.7, 'payout_expected': 30.0, 'sharpe': 0.6, 'notes': [], 'requirements': []},
        'b': {'ev_ratio': 0.8, 'roi': 0.9, 'payout_expected': 35.0, 'sharpe': 0.8, 'notes': [], 'requirements': []},
    }

    def fake_eval(tickets, bankroll, allow_heuristic=True):
        return results[tickets[0]['id']]

    monkeypatch.setattr(runner_chain, 'evaluate_combo', fake_eval)

    exotics = [
        [{'id': 'a', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}],
        [{'id': 'b', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}],
    ]

    tickets, info = runner_chain.validate_exotics_with_simwrapper(exotics, bankroll=5)
    assert len(tickets) == 1
    assert tickets[0]['legs'] == ['b']
    assert tickets[0]['flags'] == ['ALERTE_VALUE']
    assert info['flags']['combo'] is True
    assert info['flags']['ALERTE_VALUE'] is True


def test_validate_exotics_with_simwrapper_skips_unreliable(monkeypatch):
    def fake_eval(tickets, bankroll, allow_heuristic=True):
        return {
            'ev_ratio': 0.6,
            'roi': 0.6,
            'payout_expected': 30.0,
            'sharpe': 0.6,
            'notes': ['combo_probabilities_unreliable'],
            'requirements': []
        }

    monkeypatch.setattr(runner_chain, 'evaluate_combo', fake_eval)

    tickets, info = runner_chain.validate_exotics_with_simwrapper(
        [[{'id': 'unsafe', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}]],
        bankroll=5,
        sharpe_min=0.5,
    )

    assert tickets == []
    assert 'probabilities_unreliable' in info['flags']['reasons']['combo']
    assert 'combo_probabilities_unreliable' in info['notes']


def test_validate_exotics_with_simwrapper_rejects_low_sharpe(monkeypatch):
    def fake_eval(tickets, bankroll, allow_heuristic=True):
        return {
            'ev_ratio': 0.7,
            'roi': 0.8,
            'payout_expected': 30.0,
            'sharpe': 0.3,
            'notes': [],
            'requirements': []
        }

    monkeypatch.setattr(runner_chain, 'evaluate_combo', fake_eval)

    tickets, info = runner_chain.validate_exotics_with_simwrapper(
        [[{'id': 'low_sharpe', 'p': 0.5, 'odds': 2.0, 'stake': 1.0}]],
        bankroll=10,
        sharpe_min=0.5,
    )

    assert tickets == []
    assert 'sharpe_below_threshold' in info['flags']['reasons']['combo']


def test_export_tracking_csv_line(tmp_path):
    path = tmp_path / 'track.csv'
    meta = {'reunion': 'R1', 'course': 'C1', 'hippodrome': 'X', 'date': '2024-01-01', 'discipline': 'plat', 'partants': 8}
    tickets = [{'stake': 2.0, 'p': 0.4}, {'stake': 1.0, 'p': 0.3}]
    stats = {
        'ev_sp': 0.3,
        'ev_global': 0.6,
        'roi_sp': 0.2,
        'roi_global': 0.5,
        'risk_of_ruin': 0.1,
        'clv_moyen': 0.0,
        'model': 'M',
        'prob_implicite_panier': 0.55,
        'roi_reel': 0.45,
        'sharpe': 0.8,
        'drift_sign': 1,
    }

    runner_chain.export_tracking_csv_line(str(path), meta, tickets, stats, alerte=True)

    lines = path.read_text(encoding='utf-8').splitlines()
    header = lines[0].split(';')
    assert header[-1] == 'ALERTE_VALUE'
    assert {'prob_implicite_panier', 'ev_simulee_post_arrondi', 'roi_simule', 'roi_reel', 'sharpe', 'drift_sign'} <= set(header)
    assert lines[1].split(';')[-1] == 'ALERTE_VALUE'
