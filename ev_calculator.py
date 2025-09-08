"""Utility functions for expected value calculations."""

from typing import Tuple


def compute_ev_roi(p: float, odds: float, stake: float) -> Tuple[float, float]:
    """Compute expected value and ROI for a single wager.

    Parameters
    ----------
    p : float
        Probability of the wager winning.
    odds : float
        Decimal odds offered for the wager.
    stake : float
        Amount staked on the wager.

    Returns
    -------
    tuple of (float, float)
        Expected value in currency units and ROI ratio.
    """
    ev = stake * (p * (odds - 1) - (1 - p))
    roi = ev / stake if stake else 0.0
    return ev, roi
