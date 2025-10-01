import datetime as dt
import json
import logging
from pathlib import Path

import pytest

import runner_chain
from scripts import runner_chain as runner_script


def test_compute_overround_cap_flat_handicap_string_partants() -> None:
    cap = runner_chain.compute_overround_cap("Handicap de Plat", "16 partants")
    assert cap == pytest.approx(1.25)


def test_compute_overround_cap_flat_large_field() -> None:
    """Open flat races with large fields should trigger the stricter cap."""

    cap = runner_chain.compute_overround_cap("Plat", 14)

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
    assert context.get("default_cap") == pytest.approx(1.25)
    assert context.get("partants") == 16
    assert context.get("discipline") == "handicap de plat"


def test_compute_overround_cap_other_disciplines() -> None:
    cap = runner_chain.compute_overround_cap("Trot Attelé", 12)
    assert cap == pytest.approx(1.25)
    

def test_compute_overround_cap_detects_handicap_from_course_label() -> None:
    cap = runner_chain.compute_overround_cap(
        None,
        "15 partants",
        course_label="Grand Handicap de Paris",
    )
    assert cap == pytest.approx(1.25)


def test_filter_exotics_by_overround_applies_flat_cap() -> None:
    """Flat handicaps with many runners should discard high overround combos."""

    tickets = [[{"id": "combo"}]]

    filtered = runner_chain.filter_exotics_by_overround(
        tickets,
        overround=1.26,
        overround_max=1.30,
        discipline="Plat",
        partants=14,
    )

    assert filtered == []


def test_compute_overround_cap_handles_accents() -> None:
    cap = runner_chain.compute_overround_cap("Handicap de Plât", "14 partants")
    assert cap == pytest.approx(1.25) 


def test_validate_exotics_with_simwrapper_filters_and_alert(monkeypatch):
    def fake_eval(tickets, bankroll, calibration=None, allow_heuristic=True):
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
    def fake_eval(tickets, bankroll, calibration=None, allow_heuristic=True):
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

    def fake_eval(tickets, bankroll, calibration=None, allow_heuristic=True):
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
    def fake_eval(tickets, bankroll, calibration=None, allow_heuristic=True):
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
    def fake_eval(tickets, bankroll, calibration=None, allow_heuristic=True):
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


def test_validate_exotics_with_simwrapper_logs_rejected_status(monkeypatch, caplog):
    def fake_eval(tickets, bankroll, calibration=None, allow_heuristic=True):
        return {
            'status': 'KO',
            'notes': [],
        }

    monkeypatch.setattr(runner_chain, 'evaluate_combo', fake_eval)

    caplog.set_level(logging.WARNING)

    tickets, info = runner_chain.validate_exotics_with_simwrapper(
        [[{'id': 'bad_combo', 'p': 0.4, 'odds': 3.0, 'stake': 1.0}]],
        bankroll=10,
    )

    assert tickets == []
    assert info['flags']['combo'] is False
    assert any(reason.startswith('status_') for reason in info['flags']['reasons']['combo'])

    def _build_payload(phase: str) -> runner_script.RunnerPayload:
    return runner_script.RunnerPayload(
        id_course="123456",
        reunion="R1",
        course="C2",
        phase=phase,
        start_time=dt.datetime(2023, 9, 25, 15, 30),
        budget=5.0,
    )


def test_trigger_phase_result_missing_arrivee(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    payload = _build_payload("RESULT")
    caplog.set_level(logging.ERROR)

    runner_script._trigger_phase(
        payload,
        snap_dir=tmp_path,
        analysis_dir=tmp_path,
        ev_min=0.0,
        roi_min=0.0,
        mode="result",
        calibration=tmp_path / "calibration.yaml",
        calibration_available=False,
    )

    race_dir = tmp_path / "R1C2"
    arrivee_json = race_dir / "arrivee.json"
    arrivee_csv = race_dir / "arrivee_missing.csv"

    assert arrivee_json.exists()
    assert arrivee_csv.exists()
    data = json.loads(arrivee_json.read_text(encoding="utf-8"))
    assert data == {
        "status": "missing",
        "R": "R1",
        "C": "C2",
        "date": "2023-09-25",
    }
    csv_content = arrivee_csv.read_text(encoding="utf-8").strip().splitlines()
    assert csv_content == ["status;R;C;date", "missing;R1;C2;2023-09-25"]
    assert not (race_dir / "cmd_update_excel.txt").exists()
    assert any("Arrivée absente" in record.message for record in caplog.records)


def test_trigger_phase_result_with_arrivee(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    payload = _build_payload("RESULT")
    race_dir = tmp_path / "R1C2"
    race_dir.mkdir(parents=True, exist_ok=True)
    (race_dir / "arrivee_officielle.json").write_text("{}", encoding="utf-8")
    (race_dir / "tickets.json").write_text("{}", encoding="utf-8")

    caplog.set_level(logging.INFO)

    runner_script._trigger_phase(
        payload,
        snap_dir=tmp_path,
        analysis_dir=tmp_path,
        ev_min=0.0,
        roi_min=0.0,
        mode="result",
        calibration=tmp_path / "calibration.yaml",
        calibration_available=False,
    )

    cmd_path = race_dir / "cmd_update_excel.txt"
    assert cmd_path.exists()
    cmd = cmd_path.read_text(encoding="utf-8")
    assert "update_excel_with_results.py" in cmd
    assert str(race_dir / "arrivee_officielle.json") in cmd
    assert str(race_dir / "tickets.json") in cmd
    assert not any("Arrivée absente" in record.message for record in caplog.records)



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
