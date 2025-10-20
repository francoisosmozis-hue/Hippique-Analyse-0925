import pipeline_run


def test_sp_coverage_guard() -> None:
    runners = [
        {"id": "1", "odds_place": 5.0, "p_place": 0.50, "probabilities": {"p_place": 0.50}},
        {"id": "2", "odds_place": 5.0, "p_place": 0.35, "probabilities": {"p_place": 0.35}},
        {"id": "3", "odds_place": 5.0, "p_place": 0.40, "probabilities": {"p_place": 0.40}},
    ]
    ticket = {"type": "SP", "legs": [{"id": "1"}, {"id": "2"}]}
    sp, combos, notes = pipeline_run._filter_sp_and_cp_tickets(
        [ticket], [], runners, {"runners": runners}
    )
    assert sp == []
    assert combos == []
    assert any(note.startswith("coverage_fail_SigmaP<0.85") for note in notes)

    ticket_ok = {"type": "SP", "legs": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}
    sp_ok, combos_ok, notes_ok = pipeline_run._filter_sp_and_cp_tickets(
        [ticket_ok], [], runners, {"runners": runners}
    )
    assert sp_ok
    assert combos_ok == []
    assert any(note.startswith("coverage_ok_SigmaP=1.25") for note in notes_ok)


def test_overround_sum() -> None:
    horses = [{"cote": 2.5}, {"cote": 3.0}, {"cote": 4.0}]
    over = pipeline_run._overround_from_odds(horses)
    assert over is not None
    assert 0.9 < over < 1.05
