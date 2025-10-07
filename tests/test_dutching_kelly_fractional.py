import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from module_dutching_pmu import dutching_kelly_fractional


def test_stakes_sum_not_exceed_bankroll():
    odds = [2.0, 3.5, 4.0]
    probs = [0.4, 0.3, 0.3]
    bankroll = 10.0
    df = dutching_kelly_fractional(
        odds, total_stake=bankroll, probs=probs, round_to=0.01
    )
    assert isinstance(df, pd.DataFrame)
    assert df["Stake (€)"].sum() <= bankroll + 1e-6


def test_custom_prob_fallback_is_used():
    odds = [2.0, 3.0]
    df = dutching_kelly_fractional(odds, prob_fallback=lambda o: 0.5, round_to=0.01)
    assert all(abs(p - 0.5) < 1e-9 for p in df["p"])


def test_remainder_allocated_to_max_fk():
    odds = [3.35, 3.83]
    probs = [0.34, 0.32]
    df = dutching_kelly_fractional(odds, total_stake=5.0, probs=probs, round_to=0.1)
    max_fk_idx = df["f_kelly"].idxmax()
    assert df.loc[max_fk_idx, "Stake (€)"] == df["Stake (€)"].max()
    assert df["Stake (€)"].sum() == 5.0


def test_shares_sum_to_one_after_rounding():
    odds = [2.0, 3.5, 4.0]
    probs = [0.4, 0.3, 0.3]
    df = dutching_kelly_fractional(odds, total_stake=10.0, probs=probs, round_to=0.01)
    assert round(df["Part"].sum(), 10) == 1.0


def test_round_to_zero_keeps_continuous_ev():
    odds = [2.6, 4.2, 6.5]
    probs = [0.45, 0.25, 0.18]
    bankroll = 20.0

    df = dutching_kelly_fractional(odds, total_stake=bankroll, probs=probs, round_to=0)

    fk = df["f_kelly"].tolist()
    if sum(fk) <= 0:
        expected_stakes = [bankroll / len(fk)] * len(fk)
    else:
        expected_stakes = [f * bankroll for f in fk]
        total_alloc = sum(expected_stakes)
        if total_alloc > bankroll:
            factor = bankroll / total_alloc
            expected_stakes = [st * factor for st in expected_stakes]

    expected_stakes_rounded = [round(st, 2) for st in expected_stakes]
    assert df["Stake (€)"].tolist() == expected_stakes_rounded

    expected_evs = []
    for st, o, p in zip(expected_stakes, odds, probs):
        gain_net = st * (o - 1.0)
        expected_evs.append(round(p * gain_net - (1.0 - p) * st, 2))

    assert df["EV (€)"].tolist() == expected_evs
