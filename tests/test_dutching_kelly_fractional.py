from pathlib import Path
import sys
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from module_dutching_pmu import dutching_kelly_fractional


def test_stakes_sum_not_exceed_bankroll():
    odds = [2.0, 3.5, 4.0]
    probs = [0.4, 0.3, 0.3]
    bankroll = 10.0
    df = dutching_kelly_fractional(odds, total_stake=bankroll, probs=probs, round_to=0.01)
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
