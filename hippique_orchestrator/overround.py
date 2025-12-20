"""
hippique_orchestrator/overround.py - Overround and Cap Utilities.

This module provides functions for calculating market overround and for
dynamically adjusting volatility caps based on race characteristics.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)


def compute_overround_place(runners: Iterable[dict[str, Any]]) -> float:
    """
    Calculates the overround for the 'place' market.

    The overround is the sum of the implied probabilities of all outcomes.
    A value of 1.0 means a fair market. Values > 1.0 represent the
    bookmaker's margin.

    Args:
        runners: An iterable of runner dictionaries. Each dictionary is expected
                 to have a 'cote_place' key with the decimal place odds.

    Returns:
        The calculated overround for the place market, or 0.0 if it cannot be
        calculated.
    """
    implied_probabilities = []
    for runner in runners:
        if not isinstance(runner, dict):
            continue

        place_odds = runner.get("cote_place") or runner.get("odds_place")

        if place_odds is None:
            # Fallback to 'cote' if 'cote_place' is missing
            place_odds = runner.get("cote")

        try:
            odds = float(place_odds)
            if odds > 1.0:
                implied_probabilities.append(1.0 / odds)
        except (ValueError, TypeError, ZeroDivisionError):
            continue

    if not implied_probabilities:
        logger.warning("Could not calculate place overround: no valid place odds found.")
        return 0.0

    return sum(implied_probabilities)


def adaptive_cap(p_place: float | None, volatility: float | None, base_cap: float = 0.6) -> float:
    """
    Provides a placeholder for an adaptive volatility cap.

    In a real implementation, this could be adjusted based on the horse's
    place probability (p_place) or other factors. For now, it returns the
    base cap.
    Args:
    p_place: The horse's probability of placing.
    volatility: The horse's odds volatility.
    base_cap: The default base cap.

    Returns:
        The calculated cap.
    """
    # This is a simple placeholder. A more complex implementation could be:
    # if p_place and p_place > 0.5:
    #     return base_cap * 0.8 # Reduce cap for strong favorites
    # return base_cap
    return base_cap
