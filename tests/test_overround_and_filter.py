from runner_chain import should_cut_exotics
from pipeline_run import _overround_from_odds_win


def test_overround_from_odds_win_simple():
    runners = [
        {"num": 1, "odds_win": 2.0},
        {"num": 2, "odds_win": 4.0},
        {"num": 3, "odds_win": 5.0},
    ]
    # 1/2 + 1/4 + 1/5 = 0.95
    assert abs(_overround_from_odds_win(runners) - 0.95) < 1e-9


def test_should_cut_exotics_threshold():
    assert should_cut_exotics(1.31) is True
    assert should_cut_exotics(1.30) is False
    assert should_cut_exotics(None) is False
