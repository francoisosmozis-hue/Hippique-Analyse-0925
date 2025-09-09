"""Batch EV/ROI simulation helper."""
from __future__ import annotations

from typing import Any, Dict, List

from ev_calculator import compute_ev_roi


def simulate_ev_batch(tickets: List[Dict[str, Any]], bankroll: float) -> Dict[str, Any]:
    """Return EV/ROI statistics for ``tickets`` given a ``bankroll``.

    This is a thin wrapper around :func:`compute_ev_roi` using its default
    thresholds.
    """
    return compute_ev_roi(tickets, budget=bankroll)
