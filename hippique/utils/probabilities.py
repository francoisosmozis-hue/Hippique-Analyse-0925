"""Probability utilities for ROI-first workflow."""

from __future__ import annotations

from collections.abc import Iterable


def implied_prob_from_odds(odds: float) -> float:
    """Return the implied probability associated with decimal odds."""
    if odds <= 1.0:
        raise ValueError("Decimal odds must be > 1.0")
    return 1.0 / odds


def no_vig_probs(odds_list: Iterable[float]) -> list[float]:
    """Convert decimal odds into fair probabilities (remove the bookmaker vig).

    The method is the industry standard: invert each odds to get the implied
    probability, then normalise the vector so that it sums to one.  The input
    iterable may contain floats or ints; it is consumed entirely in memory.
    """

    inv = [implied_prob_from_odds(float(o)) for o in odds_list]
    total = sum(inv)
    if total <= 0:
        raise ValueError("Invalid odds list")
    return [value / total for value in inv]


def expected_value_simple(p_win: float, odds: float, stake: float) -> float:
    """Compute the expected value of a simple bet."""
    return p_win * stake * (odds - 1.0) - (1.0 - p_win) * stake
