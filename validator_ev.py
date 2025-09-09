"""Validation utilities for EV statistics."""
from __future__ import annotations

from typing import Any, Mapping


def validate_ev(stats: Mapping[str, Any]) -> bool:
    """Validate the structure and bounds of EV statistics.

    Parameters
    ----------
    stats:
        Mapping containing at least ``ev_ratio``, ``ev`` and ``roi``.

    Returns
    -------
    bool
        ``True`` when all checks pass.

    Raises
    ------
    ValueError
        If a required key is missing or a bound is violated.
    """
    required = ("ev_ratio", "ev", "roi")
    for key in required:
        if key not in stats:
            raise ValueError(f"missing '{key}' in stats")
        if not isinstance(stats[key], (int, float)):
            raise ValueError(f"'{key}' must be a number")

    ev_ratio = float(stats["ev_ratio"])
    if not 0 <= ev_ratio <= 1:
        raise ValueError("ev_ratio must be within [0, 1]")
    if ev_ratio < 0.40:
        raise ValueError("ev_ratio below minimum threshold 0.40")

    roi = float(stats["roi"])
    if roi < -1:
        raise ValueError("roi must be greater than or equal to -1")

    # ``ev`` already checked for being numeric; no additional bounds
    return True
