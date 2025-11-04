import pandas as pd
import pytest

from module_dutching_pmu import dutching_kelly_fractional, ev_panier


def test_probs_clamped_within_bounds():
    odds = [2.0, 3.0]
    probs = [-0.5, 2.0]
    df = dutching_kelly_fractional(odds, probs=probs, round_to=0.01)
    assert df["p"].tolist() == pytest.approx([0.01, 0.9])


def test_ev_panier_sum_and_empty_dataframe():
    odds = [2.0, 3.0]
    probs = [0.4, 0.3]
    df = dutching_kelly_fractional(odds, probs=probs, total_stake=10.0, round_to=0.01)
    assert ev_panier(df) == pytest.approx(df["EV (€)"].sum())
    assert ev_panier(pd.DataFrame()) == 0.0
